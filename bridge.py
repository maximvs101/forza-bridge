"""Coeur de la passerelle : reception UDP -> OSC + WebSocket.

Implementation unique partagee par `main.py` (ligne de commande) et
`gui.py` (interface graphique). Les deux points d'entree avaient auparavant
leur propre copie de cette boucle, qui avait deja diverge (canaux transmis,
emission du nom de vehicule).

L'OSC part vers UNE OU PLUSIEURS destinations : le meme flux peut alimenter
simultanement un logiciel de creation visuelle, une console lumiere et un
environnement sonore.

Le seul parametre qui differe reellement entre les deux est le filtre de
canaux : `None` = tous les champs (ligne de commande), un ensemble = la
selection de l'interface.
"""

from __future__ import annotations

import socket
import threading
import time

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.udp_client import SimpleUDPClient

import car_lookup
import derived_channels
import smoothing
# Symboles importes directement : le parametre `osc_targets` de Bridge
# masquerait un import du module homonyme.
from osc_targets import DEFAULT_TARGET, resolve as resolve_target
from channel_catalog import ALL_CHANNELS, CATEGORY_OF, UNITS
from forza_telemetry import ACCEPTED_SIZES, parse

OSC_ADDRESS_PREFIX = "/forza"

# Champs toujours joints a la charge utile WebSocket, meme s'ils ne sont pas
# selectionnes : les consommateurs web en ont besoin comme contexte de mise a
# l'echelle (sans engine_max_rpm, une jauge de regime ne peut pas se calibrer).
WS_CONTEXT_FIELDS = ("engine_max_rpm", "is_race_on")

_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def _osc_type(value):
    """Type OSC a imposer, ou None pour laisser python-osc decider.

    python-osc emet `,i` (int32) sous 2^31 et bascule sur `,h` (int64)
    au-dela. Tous les recepteurs ne decodent pas `h` de facon fiable :
    certains laissent alors le canal cesser de se mettre a jour, sans erreur.
    `timestamp_ms` franchit ce seuil apres ~24,8 jours de fonctionnement.

    On force alors le type `d` (double, 64 bits). Convertir en `float` sans
    plus de precaution ne suffit PAS : python-osc encode tout flottant
    Python en `f`, soit 32 bits, et 3000000007 arrivait a 3000000000 —
    le remede etait pire que le mal, avec un compteur de millisecondes
    quantifie par paliers de 128 a 256 ms.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        if not (_INT32_MIN <= value <= _INT32_MAX):
            return OscMessageBuilder.ARG_TYPE_DOUBLE
    return None


class Bridge(threading.Thread):
    """Ecoute le flux Forza et le retransmet en OSC (et en WebSocket).

    `selected_channels` peut etre reaffecte a tout moment depuis un autre
    thread : la boucle en prend un instantane a chaque trame. Il faut
    affecter un NOUVEL ensemble, jamais muter celui en place (une mutation
    concurrente pendant l'iteration leve `RuntimeError`).
    """

    def __init__(self, listen_port: int, osc_targets=None, *,
                 listen_host: str = "0.0.0.0",
                 selected_channels: frozenset[str] | None = None,
                 only_racing: bool = False,
                 send_car_name: bool = True,
                 ws_server=None, osc_clients=None, derived: bool = True,
                 smoothing_settings: dict[str, float] | None = None):
        super().__init__(daemon=True)
        # Canaux calcules (units usuelles, grandeurs bornees) ajoutes aux
        # canaux bruts. Voir derived_channels.py.
        self.derived = derived
        # Lissage applique APRES les derives : on peut ainsi adoucir
        # speed_kmh tout en gardant speed brut pour l'analyse.
        self.smoother = smoothing.Smoother(smoothing_settings)
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.selected_channels = selected_channels
        self.only_racing = only_racing
        self.send_car_name = send_car_name
        # `ws_server` est branche plus bas par attach_ws_server(), une fois les
        # attributs dont dependent hello() et status() en place.
        self.ws_server = None
        # Doublons retires : deux fois la meme destination ouvrirait deux
        # sockets et doublerait reellement le trafic vers le meme point.
        targets = list(dict.fromkeys(
            osc_targets if osc_targets is not None else [DEFAULT_TARGET]))
        if osc_clients is None and not targets:
            raise ValueError("no OSC destination")
        self._requested_targets = targets

        # Clients injectables pour les tests. Sinon ils sont construits dans
        # run(), PAS ici : SimpleUDPClient resout le DNS dans son
        # builder, ce qui bloquait le thread appelant (l'interface
        # graphique) et faisait remonter socket.gaierror hors de son rappel.
        self.osc_clients = list(osc_clients) if osc_clients is not None else []
        self._clients_fournis = osc_clients is not None
        # Destination -> derniere erreur rencontree, pour l'affichage.
        self.osc_failures: dict[tuple[str, int], str] = {}

        self.stop_event = threading.Event()
        self.bound = threading.Event()  # arme apres la tentative de bind
        self.latest_values: dict[str, float] = {}
        # Deux compteurs, parce qu'ils repondent a deux questions
        # differentes : `received_count` = le jeu emet-il ? `packet_count` =
        # combien de trames ont ete traitees. Avec "seulement en course", en
        # menu, le second reste a 0 alors que le jeu emet normalement —
        # l'indicateur annoncait alors "No packets from the game", ce qui
        # envoyait verifier Data Out sans raison.
        self.received_count = 0
        self.packet_count = 0
        self.error: str | None = None

        # Paquets recus mais refuses par le decodeur, avec leurs tailles. Sans
        # ce compteur, une variante de paquet inconnue (le jeu peut publier
        # l'usure des pneus, ce qui change la taille) donnait un silence
        # complet : l'interface affichait "No packets from the game" alors que
        # les paquets arrivaient. Une taille affichee est un diagnostic.
        self.rejected_count = 0
        self.rejected_sizes: dict[int, int] = {}

        self._last_ordinal: int | None = None
        self._car_name: str = "-"
        # Etabli par run(), mais defini des ici : `_emit` s'en sert, et un
        # appel avant le demarrage levait AttributeError au lieu de ne rien
        # faire.
        self._clients_by_target: list = []

        self.attach_ws_server(ws_server)

    def attach_ws_server(self, ws_server) -> None:
        """Branche (ou debranche) le serveur WebSocket.

        Le serveur ne connait pas les canaux emis : c'est le pont qui fournit
        le contenu du message d'accueil et de la trame d'etat. Passer par
        cette methode plutot que d'affecter `ws_server` directement, sinon les
        fabriques manquent : mesure sur le jeu, un serveur demarre a chaud par
        la case de l'interface annoncait alors 0 canal, aucun vehicule et
        `packets: null` — le flux de telemetrie fonctionnait, ce qui rendait le
        defaut discret.
        """
        self.ws_server = ws_server
        if ws_server is not None:
            ws_server.hello_factory = self.hello
            ws_server.status_factory = self.status

    @property
    def osc_targets(self) -> list[tuple[str, int]]:
        """Destinations demandees. Derivee, jamais stockee en double :
        l'ancien attribut annoncait la valeur par defaut alors que des
        clients injectes emettaient ailleurs."""
        return list(self._requested_targets)

    @property
    def car_name(self) -> str:
        return self._car_name

    def hello(self) -> dict:
        """Metadonnees envoyees a chaque client WebSocket qui se connecte."""
        selected = self.selected_channels
        names = list(ALL_CHANNELS) if selected is None else sorted(selected)
        # Les champs de contexte partent toujours, meme non selectionnes.
        for name in WS_CONTEXT_FIELDS:
            if name not in names:
                names.append(name)
        units = {n: UNITS[n] for n in names if n in UNITS}
        categories = {n: CATEGORY_OF[n] for n in names if n in CATEGORY_OF}

        # Les canaux lisses portent l'unite et la categorie de leur source.
        for smoothed in self.smoother.produced_channels:
            if smoothed in names:
                continue
            names.append(smoothed)
            source = smoothed[:-len(smoothing.SUFFIX)]
            if source in UNITS:
                units[smoothed] = UNITS[source]
            if source in CATEGORY_OF:
                categories[smoothed] = CATEGORY_OF[source]

        return {
            "channels": names,
            "units": units,
            "categories": categories,
            "car_name": self._car_name,
            "packet_count": self.packet_count,
        }

    def stop(self) -> None:
        self.stop_event.set()

    def _build_clients(self) -> None:
        """Resout chaque destination une fois, puis ouvre les sockets.

        La resolution est faite ici pour deux raisons : ne pas figer le thread
        appelant, et surtout ne pas laisser python-osc re-resoudre le nom a
        chaque datagramme — il jette le resultat de sa propre resolution et
        repasse la chaine d'origine a `sendto`.
        """
        clients = []
        for target in self._requested_targets:
            try:
                hote, port = resolve_target(target)
            except OSError as exc:
                # Une destination injoignable ne doit pas empecher les autres
                # de fonctionner : on la note et on continue.
                self.osc_failures[target] = f"cannot resolve: {exc}"
                continue
            clients.append((target, SimpleUDPClient(hote, port)))
        self._clients_by_target = clients
        self.osc_clients = [client for _, client in clients]

    def _close_clients(self) -> None:
        """Ferme les sockets OSC ouverts par le pont.

        Un client par destination et par demarrage : sans fermeture, chaque
        cycle Start/Stop laissait un socket UDP ouvert jusqu'au passage du
        ramasse-miettes (ResourceWarning visible en test). `SimpleUDPClient`
        expose bien un `close()` public.

        Les clients INJECTES appartiennent a l'appelant : on n'y touche pas.
        """
        if self._clients_fournis:
            return
        for client in self.osc_clients:
            fermer = getattr(client, "close", None)
            if not callable(fermer):
                continue
            try:
                fermer()
            except Exception:  # noqa: BLE001 - une fermeture ne doit rien casser
                pass

    def run(self) -> None:
        try:
            self._execute()
        finally:
            # Toutes les sorties passent par ici, l'echec de bind compris :
            # sinon un port deja pris laissait les sockets OSC ouverts.
            self._close_clients()

    def _execute(self) -> None:
        if not self._clients_fournis:
            self._build_clients()
            if not self.osc_clients:
                self.error = ("no reachable OSC destination: "
                              + " ; ".join(self.osc_failures.values()))
                self.bound.set()
                return
        else:
            # Chaque client doit etre servi, meme si la liste des targets est
            # plus courte : un `zip` tronquerait a la plus courte des deux et
            # les clients au-dela ne recevraient jamais rien.
            targets = self._requested_targets
            self._clients_by_target = [
                (targets[indice] if indice < len(targets) else ("client", indice),
                 client)
                for indice, client in enumerate(self.osc_clients)]

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.listen_host, self.listen_port))
        except OSError as exc:
            self.error = str(exc)
            sock.close()
            return
        finally:
            # Toujours armer, y compris en cas d'echec, pour que l'appelant
            # qui attend cet evenement ne reste pas bloque.
            self.bound.set()

        sock.settimeout(0.5)
        try:
            self._loop(sock)
        except BaseException as exc:  # noqa: BLE001 - remonte a l'interface
            # Sans cette capture, une exception tuait le thread en silence :
            # l'interface continuait d'afficher "En ecoute" avec un compteur
            # fige alors que plus rien n'etait emis.
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            sock.close()

    def _loop(self, sock: socket.socket) -> None:
        while not self.stop_event.is_set():
            try:
                packet, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            frame = parse(packet)
            if frame is None:
                # Compte et retient la taille : c'est la seule information qui
                # permette de distinguer "le jeu n'emet pas" de "le jeu emet
                # une variante que nous ne savons pas lire".
                self.rejected_count += 1
                taille = len(packet)
                self.rejected_sizes[taille] = self.rejected_sizes.get(taille, 0) + 1
                continue

            # Compte et signale l'activite AVANT le filtre "seulement en
            # course" : sinon, en menu, l'indicateur et la trame d'etat
            # annonceraient un flux mort alors que le jeu emet normalement.
            self.received_count += 1
            if self.ws_server is not None:
                self.ws_server.note_activity()

            if self.only_racing and not frame.is_race_on:
                continue

            values = frame.values
            if self.derived:
                # Fusionnes aux canaux bruts : tout l'aval (OSC, WebSocket,
                # interface, accueil) les traite sans rien de particulier.
                values = {**values, **derived_channels.compute(values)}
            if self.smoother.active:
                values = self.smoother.apply(values, time.monotonic())
            self.latest_values = values
            self.packet_count += 1

            # Instantane : `selected_channels` peut etre reaffecte par
            # l'interface entre deux trames.
            selected = self.selected_channels
            if selected is None:
                names = values.keys()
            else:
                # Les canaux lisses ne figurent pas au catalogue : les
                # configurer vaut demande explicite, ils accompagnent donc
                # toujours la selection.
                smoothed = self.smoother.produced_channels
                names = selected if not smoothed else selected.union(smoothed)

            ordinal = values.get("car_ordinal")
            if ordinal != self._last_ordinal:
                self._last_ordinal = ordinal
                self._car_name = car_lookup.describe(ordinal)
                self.smoother.reset()
                if self.send_car_name:
                    # Chaine de caracteres : certains recepteurs OSC
                    # n'acceptent que des nombres sur leur entree principale
                    # et l'ignorent, ou exigent une entree dediee.
                    self._emit(f"{OSC_ADDRESS_PREFIX}/car_name", self._car_name)

            for name in names:
                value = values.get(name)
                if value is not None:
                    self._emit(f"{OSC_ADDRESS_PREFIX}/{name}", value)

            if self.ws_server is not None:
                # Charge utile construite paresseusement : le serveur limite
                # la cadence et n'appellera cette fabrique que s'il emet.
                self.ws_server.publish(lambda: self._ws_payload(values, names))

    def rejected_summary(self) -> str | None:
        """Phrase a afficher quand des paquets ont ete refuses, sinon None.

        Une taille inconnue n'est pas une anomalie a taire : c'est exactement
        ce qu'il faut savoir pour comprendre pourquoi rien n'arrive.
        """
        if not self.rejected_count:
            return None
        tailles = sorted(self.rejected_sizes.items(),
                         key=lambda kv: kv[1], reverse=True)
        detail = ", ".join(f"{taille} B" for taille, _ in tailles[:3])
        return (f"{self.rejected_count} packet(s) of unsupported size "
                f"({detail}); expected {sorted(ACCEPTED_SIZES)}")

    def status(self) -> dict:
        """Complement du pont a la trame d'etat periodique du serveur."""
        etat = {
            "packets": self.packet_count,
            # Distinct de `packets` quand "seulement en course" filtre.
            "packets_received": self.received_count,
            "car_name": self._car_name,
            "is_race_on": bool(self.latest_values.get("is_race_on", 0)),
        }
        # Champs absents quand tout va bien : un client n'a pas a filtrer des
        # zeros pour savoir s'il y a un probleme.
        if self.rejected_count:
            etat["rejected"] = self.rejected_count
            etat["rejected_sizes"] = dict(self.rejected_sizes)
        return etat

    def _emit(self, address: str, value) -> None:
        """Envoie un message OSC a toutes les destinations.

        Le message est encode UNE seule fois : avec plusieurs destinations,
        passer par send_message() le reconstruirait a chaque envoi.

        Chaque envoi est isole : sans cela une seule destination injoignable
        (console eteinte, lien sature) tuait le thread et arretait aussi
        toutes les autres destinations ET la diffusion WebSocket.
        """
        builder = OscMessageBuilder(address=address)
        forced_type = _osc_type(value)
        if forced_type is None:
            builder.add_arg(value)
        else:
            builder.add_arg(float(value), arg_type=forced_type)
        message = builder.build()

        for target, client in self._clients_by_target:
            try:
                client.send(message)
            except Exception as exc:  # noqa: BLE001 - une target ne doit pas tout arreter
                self.osc_failures[target] = f"{type(exc).__name__}: {exc}"
            else:
                # Efface l'echec precedent : sans cela un seul hoquet reseau
                # marquait la destination en panne pour toute la session, et
                # une vraie panne ne se distinguait plus d'un incident passe.
                # Les destinations jamais resolues, elles, ne figurent pas
                # dans `_clients_by_target` : leur echec reste affiche.
                self.osc_failures.pop(target, None)

    def _ws_payload(self, values: dict, names) -> dict:
        payload = {name: values[name] for name in names if name in values}
        for name in WS_CONTEXT_FIELDS:
            if name not in payload and name in values:
                payload[name] = values[name]
        payload["car_name"] = self._car_name
        return payload
