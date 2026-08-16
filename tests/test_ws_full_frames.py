"""Option "trames completes" par client.

Destinee aux consommateurs sans etat accumule (cables.gl traite chaque
message isolement) : en mode differentiel, un champ inchange y arriverait
"undefined".
"""

import asyncio
import json
import socket as _socket
import threading
import time
import unittest

import websockets

from tests.helpers import free_port, wait_until
from ws_server import TelemetryWebSocketServer


def port_tcp() -> int:
    return free_port(_socket.SOCK_STREAM)


class FullFramesTestCase(unittest.TestCase):
    def lance(self, **kwargs) -> TelemetryWebSocketServer:
        defauts = dict(host="127.0.0.1", port=port_tcp(), serve_assets=False,
                       status_interval=60, rate_hz=1000, differential=True,
                       resync_seconds=30)
        defauts.update(kwargs)
        self.serveur = TelemetryWebSocketServer(**defauts)
        self.assertTrue(self.serveur.start())
        self.addCleanup(self.serveur.stop)
        return self.serveur

    def produit(self, combien=25, pause=0.02):
        """Un champ bouge, deux restent figes."""
        def boucle():
            for i in range(combien):
                self.serveur.publish({"speed": float(i), "gear": 3,
                                      "engine_max_rpm": 7800.0})
                time.sleep(pause)
        threading.Thread(target=boucle, daemon=True).start()

    def collecte(self, commande, combien=5, timeout=6.0):
        trames, accuses = [], []

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}"
            async with websockets.connect(url) as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)   # hello
                await ws.send(json.dumps(commande))
                pret = False
                self.produit()
                fin = time.monotonic() + timeout
                while len(trames) < combien and time.monotonic() < fin:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                    if message.get("type") == "subscribed":
                        accuses.append(message); pret = True; continue
                    if message.get("type") == "telemetry" and pret:
                        trames.append(message)

        asyncio.run(asyncio.wait_for(client(), timeout=timeout + 8))
        return accuses, trames


class TestTramesCompletes(FullFramesTestCase):
    def test_annonce_dans_l_accueil(self):
        self.lance()

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}"
            async with websockets.connect(url) as ws:
                hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                self.assertTrue(hello["full_frames_supported"])

        asyncio.run(asyncio.wait_for(client(), timeout=10))

    def test_chaque_trame_porte_tous_les_champs(self):
        """Le coeur de la fonctionnalite : meme les champs figes sont presents."""
        self.lance()
        accuses, trames = self.collecte({"full": True})

        self.assertTrue(accuses[0]["full"])
        self.assertTrue(trames)
        for trame in trames:
            self.assertTrue(trame.get("full"))
            for champ in ("speed", "gear", "engine_max_rpm"):
                self.assertIn(champ, trame, "un champ fige manque a la trame")

    def test_mode_differentiel_omet_les_champs_figes(self):
        """Contre-epreuve : sans l'option, les champs figes disparaissent."""
        self.lance()
        _, trames = self.collecte({"subscribe": "*"})

        partielles = [t for t in trames if not t.get("full")]
        self.assertTrue(partielles, "aucune trame partielle observee")
        self.assertFalse(any("gear" in t for t in partielles),
                         "un champ fige ne devrait pas etre reemis")

    def test_combinaison_avec_un_abonnement(self):
        self.lance()
        accuses, trames = self.collecte({"subscribe": ["speed", "gear"], "full": True})

        self.assertEqual(accuses[0]["channels"], ["gear", "speed"])
        self.assertTrue(accuses[0]["full"])
        for trame in trames:
            donnees = {k for k in trame if k not in ("type", "full")}
            self.assertEqual(donnees, {"speed", "gear"},
                             "abonnement et trames completes doivent se combiner")

    def test_desactivation(self):
        self.lance()

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}"
            async with websockets.connect(url) as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)
                await ws.send(json.dumps({"full": True}))
                premier = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                self.assertTrue(premier["full"])
                await ws.send(json.dumps({"full": False}))
                second = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                self.assertFalse(second["full"])

        asyncio.run(asyncio.wait_for(client(), timeout=10))
        self.assertEqual(len(self.serveur._full_frames), 0)

    def test_oublie_a_la_deconnexion(self):
        serveur = self.lance()

        async def client():
            url = f"ws://127.0.0.1:{serveur.port}"
            async with websockets.connect(url) as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)
                await ws.send(json.dumps({"full": True}))
                await asyncio.wait_for(ws.recv(), timeout=3)

        asyncio.run(asyncio.wait_for(client(), timeout=10))
        self.assertTrue(wait_until(lambda: not serveur._full_frames, timeout=3))

    def test_clients_mixtes_servis_correctement(self):
        """Un client differentiel et un client "complet" partagent la meme
        diffusion : chacun doit recevoir sa forme."""
        serveur = self.lance()
        recu_diff, recu_plein = [], []
        pret = threading.Event()

        async def deux_clients():
            url = f"ws://127.0.0.1:{serveur.port}"
            async with websockets.connect(url) as a, websockets.connect(url) as b:
                await asyncio.wait_for(a.recv(), timeout=3)
                await asyncio.wait_for(b.recv(), timeout=3)
                await b.send(json.dumps({"full": True}))
                # accuse de b
                while True:
                    m = json.loads(await asyncio.wait_for(b.recv(), timeout=3))
                    if m.get("type") == "subscribed":
                        break
                pret.set()

                async def lire(ws, cible):
                    fin = time.monotonic() + 4
                    while len(cible) < 4 and time.monotonic() < fin:
                        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                        if m.get("type") == "telemetry":
                            cible.append(m)

                self.produit(combien=60)
                await asyncio.gather(lire(a, recu_diff), lire(b, recu_plein))

        asyncio.run(asyncio.wait_for(deux_clients(), timeout=20))

        self.assertTrue(recu_plein)
        for trame in recu_plein:
            self.assertIn("gear", trame, "le client 'complet' doit tout recevoir")
        partielles = [t for t in recu_diff if not t.get("full")]
        self.assertTrue(partielles)
        self.assertFalse(any("gear" in t for t in partielles),
                         "le client differentiel ne doit pas recevoir les champs figes")


if __name__ == "__main__":
    unittest.main()
