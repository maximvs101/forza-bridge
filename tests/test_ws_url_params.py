"""Reglages passes dans l'URL de connexion.

Voie indispensable pour les clients incapables d'envoyer une commande au bon
moment : certains signalent la connexion comme etablie avant que l'objet de
connexion ne soit utilisable, si bien qu'une commande envoyee a cet instant
part dans le vide et se perd en silence.
"""

import asyncio
import json
import socket as _socket
import threading
import time
import unittest

import websockets

from tests.helpers import free_port
from ws_server import TelemetryWebSocketServer


def port_tcp() -> int:
    return free_port(_socket.SOCK_STREAM)


class UrlTestCase(unittest.TestCase):
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
        def boucle():
            for i in range(combien):
                self.serveur.publish({"speed": float(i), "gear": 3,
                                      "car_name": "Audi R8 GT"})
                time.sleep(pause)
        threading.Thread(target=boucle, daemon=True).start()

    def collecte(self, requete, combien=5, timeout=6.0):
        hello = {}
        trames = []

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}{requete}"
            async with websockets.connect(url) as ws:
                hello.update(json.loads(await asyncio.wait_for(ws.recv(), timeout=3)))
                self.produit()
                fin = time.monotonic() + timeout
                while len(trames) < combien and time.monotonic() < fin:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                    if m.get("type") == "telemetry":
                        trames.append(m)

        asyncio.run(asyncio.wait_for(client(), timeout=timeout + 8))
        return hello, trames


class TestParametreFull(UrlTestCase):
    def test_full_active_les_trames_completes(self):
        self.lance()
        hello, trames = self.collecte("/?full=1")
        self.assertTrue(hello["full"])
        self.assertTrue(trames)
        for trame in trames:
            self.assertIn("car_name", trame,
                          "un champ fige doit figurer dans chaque trame")

    def test_sans_parametre_le_differentiel_s_applique(self):
        """Contre-epreuve : sinon le test precedent passerait sans rien prouver."""
        self.lance()
        hello, trames = self.collecte("/")
        self.assertFalse(hello["full"])
        partielles = [t for t in trames if not t.get("full")]
        self.assertTrue(partielles)
        self.assertFalse(any("car_name" in t for t in partielles))

    def test_valeurs_negatives_ignorees(self):
        self.lance()
        for requete in ("/?full=0", "/?full=false", "/?full="):
            with self.subTest(requete=requete):
                hello, _ = self.collecte(requete, combien=1)
                self.assertFalse(hello["full"])


class TestParametreChannels(UrlTestCase):
    def test_restreint_les_canaux(self):
        self.lance()
        hello, trames = self.collecte("/?channels=speed,gear&full=1")
        self.assertEqual(hello["channels"], ["gear", "speed"])
        self.assertTrue(trames)
        for trame in trames:
            donnees = {k for k in trame if k not in ("type", "full")}
            self.assertEqual(donnees, {"speed", "gear"})

    def test_accueil_coherent_avec_l_abonnement(self):
        """L'accueil ne doit pas annoncer des canaux que ce client ne
        recevra jamais."""
        serveur = self.lance()
        serveur.hello_factory = lambda: {
            "channels": ["speed", "gear", "boost"],
            "units": {"speed": "m/s", "gear": "rapport", "boost": "sans dimension"},
            "categories": {"speed": "Position", "gear": "Controls", "boost": "Controls"},
        }
        hello, _ = self.collecte("/?channels=speed", combien=1)
        self.assertEqual(hello["channels"], ["speed"])
        self.assertEqual(set(hello["units"]), {"speed"})
        self.assertEqual(set(hello["categories"]), {"speed"})

    def test_etoile_revient_a_tout(self):
        self.lance()
        hello, _ = self.collecte("/?channels=*", combien=1)
        self.assertNotIn("channels", hello)

    def test_espaces_et_entrees_vides_tolerees(self):
        self.lance()
        hello, _ = self.collecte("/?channels=%20speed%20,,gear%20", combien=1)
        self.assertEqual(hello["channels"], ["gear", "speed"])


class TestNettoyage(UrlTestCase):
    def test_reglages_oublies_a_la_deconnexion(self):
        serveur = self.lance()
        self.collecte("/?channels=speed&full=1", combien=1)
        deadline = time.monotonic() + 3
        while (serveur._full_frames or serveur._subscriptions) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(serveur._full_frames), 0)
        self.assertEqual(len(serveur._subscriptions), 0)


if __name__ == "__main__":
    unittest.main()
