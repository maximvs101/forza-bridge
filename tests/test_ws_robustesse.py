"""Robustesse des chemins ajoutes avec la trame d'etat et l'abonnement.

Ces cas correspondent a des defauts trouves en relecture : chacun passait
la suite precedente.
"""

import asyncio
import json
import socket as _socket
import threading
import time
import unittest

import websockets

from bridge import Bridge
from tests.helpers import OscRecorder, free_port, make_packet, wait_until
from ws_server import TelemetryWebSocketServer


def port_tcp() -> int:
    return free_port(_socket.SOCK_STREAM)


class TestBattementIndestructible(unittest.TestCase):
    """Personne n'attend la tache du battement : une exception l'arreterait
    pour toute la duree de vie du serveur, sans le moindre signe."""

    def lance(self, **kwargs):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                           serve_assets=False, **kwargs)
        self.assertTrue(serveur.start())
        self.addCleanup(serveur.stop)
        return serveur

    def recolte_status(self, serveur, combien=2, timeout=6.0):
        recus = []

        async def client():
            url = f"ws://127.0.0.1:{serveur.port}"
            async with websockets.connect(url) as ws:
                fin = time.monotonic() + timeout
                while len(recus) < combien and time.monotonic() < fin:
                    brut = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    message = json.loads(brut)
                    if message.get("type") == "status":
                        recus.append(message)

        asyncio.run(asyncio.wait_for(client(), timeout=timeout + 5))
        return recus

    def test_valeur_non_serialisable_ne_tue_pas_le_battement(self):
        serveur = self.lance(status_interval=0.2)
        serveur.status_factory = lambda: {"objet": object()}
        # Le battement doit survivre et continuer a emettre.
        self.assertGreaterEqual(len(self.recolte_status(serveur, combien=2)), 2)

    def test_nan_ne_produit_pas_de_json_invalide(self):
        serveur = self.lance(status_interval=0.2)
        serveur.status_factory = lambda: {"mesure": float("nan")}
        etats = self.recolte_status(serveur, combien=1)
        self.assertEqual(etats[0]["mesure"], None)


class TestActiviteAvecOnlyRacing(unittest.TestCase):
    """Avec --only-racing, les paquets hors course sont ecartes avant l'envoi.

    Si l'activite n'etait notee qu'a l'emission, la trame d'etat annoncerait
    un flux mort pendant tout le temps passe dans les menus.
    """

    def test_menu_reste_un_flux_vivant(self):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                            serve_assets=False, status_interval=0.2,
                                            stale_after=1.0)
        self.assertTrue(serveur.start())
        self.addCleanup(serveur.stop)

        port = free_port()
        pont = Bridge(listen_port=port, only_racing=True, ws_server=serveur,
                      osc_clients=[OscRecorder()])
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        self.addCleanup(lambda: (pont.stop(), pont.join(timeout=3)))

        arret = threading.Event()

        def emetteur():
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            while not arret.is_set():
                # is_race_on = 0 : ecarte par le filtre, mais bien recu
                sock.sendto(make_packet(is_race_on=0), ("127.0.0.1", port))
                time.sleep(0.02)
            sock.close()

        threading.Thread(target=emetteur, daemon=True).start()
        self.addCleanup(arret.set)

        recus = []

        async def client():
            url = f"ws://127.0.0.1:{serveur.port}"
            async with websockets.connect(url) as ws:
                fin = time.monotonic() + 5
                while time.monotonic() < fin:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    if message.get("type") == "status":
                        recus.append(message)
                        if len(recus) >= 2:
                            return

        asyncio.run(asyncio.wait_for(client(), timeout=12))
        self.assertTrue(recus)
        self.assertEqual(pont.packet_count, 0, "les paquets doivent bien etre filtres")
        self.assertTrue(recus[-1]["receiving"],
                        "flux filtre pris a tort pour un flux mort")


class TestContrePression(unittest.TestCase):
    """Le garde-fou est teste directement : un vrai client qui ne lit rien
    bloque aussi la poignee de fermeture, ce qui fait expirer le test sans
    rien prouver sur le mecanisme."""

    def test_un_client_bloque_ne_fait_pas_gonfler_la_file(self):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                            serve_assets=False)

        class ClientBloque:
            """Son envoi ne se termine jamais, comme un client sature."""

            def __init__(self):
                self.envois = 0

            async def send(self, message):
                self.envois += 1
                await asyncio.Event().wait()

        async def scenario():
            lent = ClientBloque()
            suivi = {}
            for _ in range(50):
                serveur._planifie(lent, "x", suivi)
                await asyncio.sleep(0)  # laisse la tache demarrer
            # Mesure DANS la boucle : a sa fermeture, asyncio annule les taches
            # en vol, le rappel de fin s'execute et vide le suivi.
            return lent.envois, len(suivi)

        envois, en_vol = asyncio.run(scenario())
        self.assertEqual(en_vol, 1, "une seule tache en vol par client")
        self.assertEqual(envois, 1, "les trames suivantes sont abandonnees")
        self.assertGreaterEqual(serveur.dropped_count, 49)

    def test_le_suivi_se_libere_quand_l_envoi_aboutit(self):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                            serve_assets=False)

        class ClientRapide:
            def __init__(self):
                self.envois = 0

            async def send(self, message):
                self.envois += 1

        async def scenario():
            rapide = ClientRapide()
            suivi = {}
            for _ in range(5):
                serveur._planifie(rapide, "x", suivi)
                await asyncio.sleep(0.01)
            return rapide, suivi

        rapide, suivi = asyncio.run(scenario())
        self.assertEqual(rapide.envois, 5)
        self.assertEqual(len(suivi), 0, "le suivi doit se vider apres chaque envoi")


class TestNettoyage(unittest.TestCase):
    def test_suivis_vides_apres_deconnexion(self):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                            serve_assets=False, status_interval=0.1)
        self.assertTrue(serveur.start())
        self.addCleanup(serveur.stop)

        async def client():
            url = f"ws://127.0.0.1:{serveur.port}"
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({"subscribe": ["speed"]}))
                await asyncio.sleep(0.4)

        asyncio.run(asyncio.wait_for(client(), timeout=10))
        self.assertTrue(wait_until(
            lambda: not serveur._subscriptions and not serveur._status_pending
                    and not serveur._pending, timeout=3))


if __name__ == "__main__":
    unittest.main()
