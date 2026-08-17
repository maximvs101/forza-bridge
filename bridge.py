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
from channel_catalog import ALL_CHANNELS, CATEGORY_OF, UNITS
from forza_telemetry import parse

OSC_ADDRESS_PREFIX = "/forza"

# Champs toujours joints a la charge utile WebSocket, meme s'ils ne sont pas
# selectionnes : les consommateurs web en ont besoin comme contexte de mise a
# l'echelle (sans engine_max_rpm, une jauge de regime ne peut pas se calibrer).
WS_CONTEXT_FIELDS = ("engine_max_rpm", "is_race_on")

_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def _osc_safe(value):
    """Evite qu'un entier non signe 32 bits change l'etiquette de type OSC.

    python-osc emet `,i` (int32) sous 2^31 et bascule sur `,h` (int64)
    au-dela. Tous les recepteurs ne decodent pas `h` de facon fiable — l'OSC
    In CHOP de TouchDesigner, par exemple, laisse alors le canal cesser de se
    mettre a jour sans erreur. `timestamp_ms` franchit ce seuil apres
    ~24,8 jours de fonctionnement.
    Un float64 represente exactement tout entier jusqu'a 2^53.
    """
    if isinstance(value, int) and not (_INT32_MIN <= value <= _INT32_MAX):
        return float(value)
    return value


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
        # Canaux calcules (unites usuelles, grandeurs bornees) ajoutes aux
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
        self.ws_server = ws_server
        # Injectables pour les tests : construire puis remplacer laissait une
        # socket UDP ouverte derriere soi.
        self.osc_targets = list(osc_targets or [("127.0.0.1", 7000)])
        self.osc_clients = list(osc_clients) if osc_clients is not None else [
            SimpleUDPClient(hote, port) for hote, port in self.osc_targets]

        self.stop_event = threading.Event()
        self.bound = threading.Event()  # arme apres la tentative de bind
        self.latest_values: dict[str, float] = {}
        self.packet_count = 0
        self.error: str | None = None

        self._last_ordinal: int | None = None
        self._car_name: str = "-"

        # Le serveur ne connait pas les canaux emis : c'est le pont qui
        # fournit le contenu du message d'accueil.
        if ws_server is not None:
            ws_server.hello_factory = self.hello
            ws_server.status_factory = self.status

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
        unites = {n: UNITS[n] for n in names if n in UNITS}
        categories = {n: CATEGORY_OF[n] for n in names if n in CATEGORY_OF}

        # Les canaux lisses portent l'unite et la categorie de leur source.
        for lisse in self.smoother.canaux_produits:
            if lisse in names:
                continue
            names.append(lisse)
            source = lisse[:-len(smoothing.SUFFIXE)]
            if source in UNITS:
                unites[lisse] = UNITS[source]
            if source in CATEGORY_OF:
                categories[lisse] = CATEGORY_OF[source]

        return {
            "channels": names,
            "units": unites,
            "categories": categories,
            "car_name": self._car_name,
            "packet_count": self.packet_count,
        }

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
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
                continue

            # Signale l'activite AVANT le filtre "seulement en course" : sinon,
            # en menu, la trame d'etat annoncerait un flux mort alors que le
            # jeu emet normalement.
            if self.ws_server is not None:
                self.ws_server.note_activity()

            if self.only_racing and not frame.is_race_on:
                continue

            values = frame.values
            if self.derived:
                # Fusionnes aux canaux bruts : tout l'aval (OSC, WebSocket,
                # interface, accueil) les traite sans rien de particulier.
                values = {**values, **derived_channels.compute(values)}
            if self.smoother.actif:
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
                lisses = self.smoother.canaux_produits
                names = selected if not lisses else selected.union(lisses)

            ordinal = values.get("car_ordinal")
            if ordinal != self._last_ordinal:
                self._last_ordinal = ordinal
                self._car_name = car_lookup.describe(ordinal)
                self.smoother.reset()
                if self.send_car_name:
                    # Chaine de caracteres : certains recepteurs n'acceptent
                    # que des nombres sur leur entree principale (dans
                    # TouchDesigner par exemple, il faut un OSC In DAT).
                    self._emet(f"{OSC_ADDRESS_PREFIX}/car_name", self._car_name)

            for name in names:
                value = values.get(name)
                if value is not None:
                    self._emet(f"{OSC_ADDRESS_PREFIX}/{name}", _osc_safe(value))

            if self.ws_server is not None:
                # Charge utile construite paresseusement : le serveur limite
                # la cadence et n'appellera cette fabrique que s'il emet.
                self.ws_server.publish(lambda: self._ws_payload(values, names))

    def status(self) -> dict:
        """Complement du pont a la trame d'etat periodique du serveur."""
        return {
            "packets": self.packet_count,
            "car_name": self._car_name,
            "is_race_on": bool(self.latest_values.get("is_race_on", 0)),
        }

    def _emet(self, adresse: str, valeur) -> None:
        """Envoie un message OSC a toutes les destinations.

        Le message est encode UNE seule fois : avec plusieurs destinations,
        passer par send_message() le reconstruirait a chaque envoi.
        """
        constructeur = OscMessageBuilder(address=adresse)
        constructeur.add_arg(valeur)
        message = constructeur.build()
        for client in self.osc_clients:
            client.send(message)

    def _ws_payload(self, values: dict, names) -> dict:
        payload = {name: values[name] for name in names if name in values}
        for name in WS_CONTEXT_FIELDS:
            if name not in payload and name in values:
                payload[name] = values[name]
        payload["car_name"] = self._car_name
        return payload
