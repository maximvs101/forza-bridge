"""Serveur WebSocket de diffusion de la telemetrie Forza.

Complement a la sortie OSC : ouvre l'acces aux outils web (cables.gl,
overlay OBS, three.js, p5.js...) qui ne parlent pas OSC.

Le serveur tourne dans son propre thread avec sa propre boucle asyncio,
pour ne pas bloquer la reception UDP. Le code appelant appelle `publish()`
a chaque trame recue ; la cadence d'emission reelle est plafonnee par
`rate_hz`. Defaut 60 Hz : c'est un PLAFOND, pas une cadence imposee.

Forza emet un paquet par image rendue : mesure du 16 aout 2026 sur FH6,
60 Hz a l'arret ou en menu (paquets alors tous identiques), mais 30 Hz en
roulant. Le plafond a 60 ne s'applique donc pas en conduite aujourd'hui ;
il est la pour ne rien perdre si le jeu tourne plus vite. Le baisser a 30
n'a d'interet que pour diffuser vers une autre machine, ou vers un client
qui redessine a la reception au lieu de passer par requestAnimationFrame.

ECOUTE LOCALE PAR DEFAUT (`127.0.0.1`). Le flux contient la position du
vehicule : `host="0.0.0.0"` l'expose a tout le reseau local et ne doit etre
utilise que sciemment, pour afficher l'overlay depuis une autre machine.
Meme en local, une page web quelconque peut se connecter a un WebSocket
localhost (la politique de meme origine ne s'y applique pas) : passer
`allowed_origins` pour restreindre par en-tete Origin.

Chaque message est un objet JSON : {"speed": 42.1, "gear": 3, ...}
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time

import websockets
from websockets.asyncio.server import serve

import http_assets


_MISSING = object()


def _changed(old, new, epsilon: float) -> bool:
    """Vrai si la valeur doit etre reemise.

    Les flottants du jeu vibrent en permanence autour de leur valeur (glissement
    de pneu, vibrations de surface) : une comparaison stricte les ferait tous
    repartir a chaque trame et annulerait l'interet du differentiel.
    """
    if old is _MISSING:
        return True
    if isinstance(new, float) and isinstance(old, float):
        return abs(new - old) > epsilon
    return old != new


def _json_safe(payload: dict) -> dict:
    """Remplace les flottants non finis par None.

    `json.dumps` accepte NaN/Infinity par defaut et emet des jetons `NaN`
    et `Infinity` qui ne sont PAS du JSON valide : `JSON.parse` les rejette,
    et la trame est perdue en silence cote navigateur.
    """
    cleaned = {}
    for key, value in payload.items():
        if isinstance(value, float) and not math.isfinite(value):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


class TelemetryWebSocketServer:
    """Diffuse les trames de telemetrie a tous les clients WebSocket connectes."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765,
                 rate_hz: float = 60.0, allowed_origins=None,
                 hello_factory=None, serve_assets: bool = True,
                 differential: bool = True, epsilon: float = 1e-4,
                 resync_seconds: float = 2.0, status_interval: float = 1.0,
                 stale_after: float = 1.5, status_factory=None):
        self.host = host
        self.port = port
        self.rate_hz = rate_hz
        self.min_interval = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self.allowed_origins = allowed_origins

        # Emission differentielle : la plupart des 88 champs ne bougent jamais
        # (voiture, cylindree, regime max, numero de tour...). N'emettre que
        # les variations retire l'essentiel du trafic.
        self.differential = differential
        self.epsilon = epsilon
        # Renvoi periodique de l'etat complet. Indispensable, pas cosmetique :
        # une trame peut etre abandonnee pour un client lent (voir _broadcast),
        # et sans resynchronisation ce client resterait faux jusqu'a la
        # prochaine variation du champ perdu.
        self.resync_seconds = resync_seconds

        # Trame d'etat periodique. Sans elle, un flux qui s'arrete se traduit
        # par un simple silence : le client ne distingue pas "jeu en pause" de
        # "pont mort". L'emission differentielle rend ce silence plus frequent.
        self.status_interval = status_interval
        self.stale_after = stale_after
        self.status_factory = status_factory

        self._state: dict = {}
        self._state_lock = threading.Lock()
        self._next_full = 0.0
        self._last_publish = 0.0
        # connexion -> ensemble de canaux, ou None pour "tout"
        self._subscriptions: dict = {}
        self._status_tasks: set = set()
        # Fabrique du message d'accueil, fournie par le pont (seul a connaitre
        # les canaux reellement emis). Facultative : sans elle, un accueil
        # minimal est envoye quand meme.
        self.hello_factory = hello_factory
        self.serve_assets = serve_assets

        self._clients: set = set()
        self._pending: dict = {}  # connexion -> tache d'envoi en cours
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_future: asyncio.Future | None = None

        self._next_send = 0.0
        self.error: str | None = None
        self.sent_count = 0
        self.dropped_count = 0

    # -- cycle de vie -----------------------------------------------------

    def start(self, timeout: float = 5.0) -> bool:
        """Demarre le serveur. Renvoie True si l'ecoute est effective."""
        if self._thread is not None:
            return True
        self._ready.clear()
        self.error = None
        self._loop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.error = self.error or "delai de demarrage depasse"
        if self.error is not None or self._loop is None:
            self._thread = None
            return False
        return True

    def stop(self) -> None:
        if self._loop is None:
            self._thread = None
            return
        loop, stop_future = self._loop, self._stop_future
        if stop_future is not None:
            loop.call_soon_threadsafe(
                lambda: stop_future.done() or stop_future.set_result(None)
            )
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._loop = None

    def _run(self) -> None:
        try:
            asyncio.run(self._serve_forever())
        except BaseException as exc:  # noqa: BLE001
            # Anciennement `except OSError`, ce qui laissait passer par ex.
            # OverflowError sur un port hors plage : `start()` renvoyait alors
            # True alors que rien n'ecoutait.
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._ready.set()

    async def _serve_forever(self) -> None:
        kwargs = {}
        if self.allowed_origins is not None:
            kwargs["origins"] = self.allowed_origins
        if self.serve_assets:
            # Sert l'overlay en HTTP sur ce meme port : plus besoin d'un
            # second serveur de fichiers a cote.
            kwargs["process_request"] = http_assets.process_request
        # `_loop` n'est publie qu'une fois l'ecoute reellement etablie :
        # sinon un echec de `serve()` laissait un loop non nul derriere lui.
        async with serve(self._handle_client, self.host, self.port, **kwargs):
            loop = asyncio.get_running_loop()
            self._stop_future = loop.create_future()
            self._loop = loop
            self._ready.set()
            battement = loop.create_task(self._status_loop())
            try:
                await self._stop_future
            finally:
                battement.cancel()

    async def _status_loop(self) -> None:
        """Emet une trame d'etat a intervalle regulier, quoi qu'il arrive.

        Elle sert de battement de coeur : son absence prolongee signale au
        client que le pont lui-meme s'est arrete, ce qu'un flux simplement
        silencieux ne permet pas de distinguer.
        """
        while True:
            await asyncio.sleep(self.status_interval)
            if not self._clients:
                continue
            message = json.dumps(self._status_payload(), separators=(",", ":"))
            for connection in list(self._clients):
                tache = asyncio.create_task(self._safe_send(connection, message))
                # Reference forte : une tache seulement referencee par la
                # boucle peut etre ramassee par le GC en cours d'execution.
                self._status_tasks.add(tache)
                tache.add_done_callback(self._status_tasks.discard)

    def _status_payload(self) -> dict:
        inactif = time.monotonic() - self._last_publish if self._last_publish else None
        etat = {
            "type": "status",
            # False = plus aucun paquet du jeu n'arrive (jeu ferme, Data Out
            # coupe). Des paquets qui arrivent sans rien faire varier (menu,
            # voiture a l'arret) restent "receiving": true.
            "receiving": inactif is not None and inactif <= self.stale_after,
            "idle_ms": None if inactif is None else int(inactif * 1000),
            "clients": len(self._clients),
        }
        if self.status_factory is not None:
            try:
                etat.update(self.status_factory())
            except Exception:  # noqa: BLE001 - un etat degrade vaut mieux que rien
                pass
        return etat

    async def _handle_client(self, connection) -> None:
        self._clients.add(connection)
        try:
            # Message d'accueil : schema, unites et cadence, pour qu'un client
            # n'ait pas a coder en dur la liste des canaux.
            hello = {"type": "hello", "protocol": 1, "source": "forza-td-bridge",
                     "rate_hz": self.rate_hz,
                     # Le client DOIT fusionner les trames partielles quand
                     # ceci vaut true ; les trames completes portent "full".
                     "differential": self.differential,
                     "resync_seconds": self.resync_seconds,
                     "status_interval": self.status_interval,
                     # Le client peut restreindre ce qu'il recoit en envoyant
                     # {"subscribe": ["speed", "gear"]} ; {"subscribe": "*"}
                     # revient a tout recevoir.
                     "subscribe_supported": True}
            if self.hello_factory is not None:
                try:
                    hello.update(self.hello_factory())
                except Exception:  # noqa: BLE001 - un accueil degrade vaut mieux que rien
                    pass
            await connection.send(json.dumps(hello, separators=(",", ":")))

            # Puis l'etat complet, immediatement : sans cela un client qui se
            # connecte a l'arret (menu, voiture immobile) reste vide jusqu'a la
            # reprise du flux, et en differentiel il lui manquerait la base sur
            # laquelle appliquer les trames suivantes.
            snapshot = self._full_state_message()
            if snapshot is not None:
                await connection.send(snapshot)

            # Puis on ecoute les commandes du client (abonnement).
            async for brut in connection:
                await self._handle_command(connection, brut)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(connection)
            self._pending.pop(connection, None)
            self._subscriptions.pop(connection, None)

    async def _handle_command(self, connection, brut) -> None:
        """Traite une commande client. Tout ce qui n'est pas reconnu est ignore."""
        try:
            commande = json.loads(brut)
        except (TypeError, ValueError):
            return
        if not isinstance(commande, dict) or "subscribe" not in commande:
            return

        demande = commande["subscribe"]
        if demande is None or demande == "*":
            self._subscriptions.pop(connection, None)
            retenus = None
        elif isinstance(demande, list):
            self._subscriptions[connection] = frozenset(
                str(nom) for nom in demande if isinstance(nom, (str, int, float)))
            retenus = sorted(self._subscriptions[connection])
        else:
            return

        await connection.send(json.dumps(
            {"type": "subscribed", "channels": retenus}, separators=(",", ":")))
        # Etat complet filtre : le client a besoin d'une base immediate sur
        # laquelle appliquer les trames partielles suivantes.
        snapshot = self._full_state_message(self._subscriptions.get(connection))
        if snapshot is not None:
            await connection.send(snapshot)

    # -- diffusion --------------------------------------------------------

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, payload) -> bool:
        """Diffuse une trame si le plafond de cadence le permet.

        `payload` peut etre un dict ou une fabrique sans argument : dans ce
        second cas elle n'est appelee que si la trame part reellement, ce qui
        evite de construire une charge utile destinee a etre jetee.
        """
        # Horodate AVANT toute sortie anticipee : c'est ce qui permet a la
        # trame d'etat de distinguer "plus aucun paquet n'arrive" de "des
        # paquets arrivent mais rien ne change".
        self._last_publish = time.monotonic()

        if self._loop is None or not self._clients:
            return False

        # Cadence planifiee, et non "temps ecoule depuis le dernier envoi" :
        # cette seconde forme derive. La source etant a 60 Hz, un intervalle
        # de 33,3 ms tombe systematiquement juste avant le paquet suivant,
        # ce qui fait sauter une trame sur deux et donne 20-24 Hz au lieu de 30.
        now = time.monotonic()
        if now < self._next_send:
            return False
        target = self._next_send + self.min_interval
        self._next_send = target if target > now else now + self.min_interval

        data = _json_safe(payload() if callable(payload) else payload)

        # L'etat memorise est celui REELLEMENT ENVOYE, pas la derniere valeur
        # recue : sinon les ecarts sous le seuil s'accumuleraient et le client
        # deriverait sans jamais etre corrige.
        with self._state_lock:
            full = (not self.differential) or now >= self._next_full
            if full:
                self._state.update(data)
                out = dict(self._state)
                out["full"] = True
                self._next_full = now + self.resync_seconds
            else:
                out = {}
                for key, value in data.items():
                    if _changed(self._state.get(key, _MISSING), value, self.epsilon):
                        out[key] = value
                        self._state[key] = value

        if not out:
            return False  # rien n'a bouge : aucune trame emise

        out["type"] = "telemetry"  # distingue l'accueil des trames de mesure
        try:
            message = json.dumps(out, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            self.dropped_count += 1
            return False

        self._loop.call_soon_threadsafe(self._broadcast, out, message)
        return True

    @staticmethod
    def _filtre(payload: dict, abonnement) -> dict | None:
        """Restreint une trame aux canaux demandes par un client.

        Renvoie None s'il ne reste aucune donnee : inutile de reveiller un
        client pour une trame qui ne le concerne pas.
        """
        if abonnement is None:
            return payload
        garde = {k: v for k, v in payload.items()
                 if k in abonnement or k in ("type", "full")}
        if not any(k not in ("type", "full") for k in garde):
            return None
        return garde

    def _full_state_message(self, abonnement=None) -> str | None:
        """Etat complet courant, pour amorcer un client qui vient d'arriver."""
        with self._state_lock:
            if not self._state:
                return None
            snapshot = dict(self._state)
        snapshot["type"] = "telemetry"
        snapshot["full"] = True
        filtre = self._filtre(snapshot, abonnement)
        if filtre is None:
            return None
        try:
            return json.dumps(filtre, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            return None

    def _broadcast(self, payload: dict, message: str) -> None:
        """Appele dans la boucle asyncio : `send()` est une coroutine,
        il faut donc planifier une tache par client.

        `message` est la version deja serialisee, reutilisee telle quelle pour
        les clients sans abonnement — le cas courant. Les autres exigent une
        serialisation propre, ce qui reste rentable puisque leur charge utile
        est plus petite.
        """
        for connection in list(self._clients):
            abonnement = self._subscriptions.get(connection)
            if abonnement is None:
                propre = message
            else:
                filtre = self._filtre(payload, abonnement)
                if filtre is None:
                    continue  # rien pour ce client dans cette trame
                try:
                    propre = json.dumps(filtre, separators=(",", ":"), allow_nan=False)
                except (TypeError, ValueError):
                    self.dropped_count += 1
                    continue

            previous = self._pending.get(connection)
            if previous is not None and not previous.done():
                # Client en retard (OBS reduit, Wi-Fi congestionne) : on
                # abandonne la trame plutot que d'empiler indefiniment des
                # taches et de lui servir un arriere perime.
                self.dropped_count += 1
                continue
            task = asyncio.create_task(self._safe_send(connection, propre))
            # Reference forte : une tache seulement referencee par la boucle
            # peut etre ramassee par le GC en cours d'execution.
            self._pending[connection] = task
            task.add_done_callback(
                lambda done, conn=connection: self._forget(conn, done)
            )
        self.sent_count += 1

    def _forget(self, connection, task) -> None:
        if self._pending.get(connection) is task:
            self._pending.pop(connection, None)

    async def _safe_send(self, connection, message: str) -> None:
        try:
            await connection.send(message)
        except (websockets.exceptions.ConnectionClosed, RuntimeError, OSError):
            self._clients.discard(connection)
