"""Abonnement par client et trame d'etat periodique."""

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


class ServeurTestCase(unittest.TestCase):
    def lance(self, **kwargs) -> TelemetryWebSocketServer:
        defauts = dict(host="127.0.0.1", port=port_tcp(), serve_assets=False,
                       status_interval=60)  # battement neutralise sauf demande
        defauts.update(kwargs)
        self.serveur = TelemetryWebSocketServer(**defauts)
        self.assertTrue(self.serveur.start())
        self.addCleanup(self.serveur.stop)
        return self.serveur

    def dialogue(self, scenario, duree=2.0):
        """Ouvre un client, lui applique `scenario(ws, recus)`."""
        recus = []

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}"
            async with websockets.connect(url) as ws:
                await scenario(ws, recus)

        asyncio.run(asyncio.wait_for(client(), timeout=duree + 8))
        return recus


async def lire(ws, recus, combien=1, timeout=3.0):
    for _ in range(combien):
        recus.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout)))
    return recus[-1]


async def lire_jusqua(ws, recus, type_attendu, timeout=5.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        recus.append(message)
        if message.get("type") == type_attendu:
            return message
    raise AssertionError(f"aucun message de type {type_attendu}")


class TestAbonnement(ServeurTestCase):
    def test_annonce_dans_l_accueil(self):
        self.lance()

        async def scenario(ws, recus):
            hello = await lire(ws, recus)
            self.assertTrue(hello["subscribe_supported"])

        self.dialogue(scenario)

    def test_accuse_de_reception(self):
        self.lance()

        async def scenario(ws, recus):
            await lire(ws, recus)  # hello
            await ws.send(json.dumps({"subscribe": ["speed", "gear"]}))
            reponse = await lire_jusqua(ws, recus, "subscribed")
            self.assertEqual(reponse["channels"], ["gear", "speed"])

        self.dialogue(scenario)

    def test_seuls_les_canaux_demandes_arrivent(self):
        serveur = self.lance(rate_hz=1000, differential=False)

        async def scenario(ws, recus):
            await lire(ws, recus)  # hello
            await ws.send(json.dumps({"subscribe": ["speed"]}))
            await lire_jusqua(ws, recus, "subscribed")

            def produire():
                for i in range(20):
                    serveur.publish({"speed": float(i), "gear": 3, "boost": 1.0})
                    time.sleep(0.02)

            threading.Thread(target=produire, daemon=True).start()
            trames = []
            fin = time.monotonic() + 2
            while len(trames) < 5 and time.monotonic() < fin:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                if message.get("type") == "telemetry":
                    trames.append(message)

            self.assertTrue(trames)
            for trame in trames:
                donnees = {k for k in trame if k not in ("type", "full")}
                self.assertEqual(donnees, {"speed"}, f"recu: {donnees}")

        self.dialogue(scenario, duree=4)

    def test_etat_complet_filtre_a_l_abonnement(self):
        """Le client doit recevoir immediatement une base sur laquelle
        appliquer les trames partielles suivantes."""
        serveur = self.lance()
        serveur._state = {"speed": 12.0, "gear": 2, "boost": 0.5}

        async def scenario(ws, recus):
            await lire(ws, recus)   # hello
            await lire(ws, recus)   # etat complet non filtre
            await ws.send(json.dumps({"subscribe": ["speed"]}))
            await lire_jusqua(ws, recus, "subscribed")
            complet = await lire_jusqua(ws, recus, "telemetry")
            self.assertTrue(complet["full"])
            self.assertEqual({k for k in complet if k not in ("type", "full")}, {"speed"})

        self.dialogue(scenario)

    def test_etoile_revient_a_tout_recevoir(self):
        serveur = self.lance(rate_hz=1000, differential=False)

        async def scenario(ws, recus):
            await lire(ws, recus)
            await ws.send(json.dumps({"subscribe": ["speed"]}))
            await lire_jusqua(ws, recus, "subscribed")
            await ws.send(json.dumps({"subscribe": "*"}))
            reponse = await lire_jusqua(ws, recus, "subscribed")
            self.assertIsNone(reponse["channels"])

            threading.Thread(
                target=lambda: [serveur.publish({"speed": 1.0, "gear": 2}) or time.sleep(0.02)
                                for _ in range(20)],
                daemon=True).start()
            trame = await lire_jusqua(ws, recus, "telemetry")
            self.assertIn("gear", trame)

        self.dialogue(scenario, duree=4)

    def test_commande_invalide_ignoree(self):
        """Le serveur lit des donnees venues du reseau : rien d'inattendu ne
        doit le faire tomber."""
        serveur = self.lance(rate_hz=1000, differential=False)

        async def scenario(ws, recus):
            await lire(ws, recus)
            for brut in ('pas du json', '[]', '{"subscribe": 42}',
                         '{"autre": 1}', '{"subscribe": {"a": 1}}', 'null'):
                await ws.send(brut)
            await asyncio.sleep(0.3)
            # la connexion tient et le flux continue
            threading.Thread(
                target=lambda: [serveur.publish({"speed": 1.0}) or time.sleep(0.02)
                                for _ in range(20)],
                daemon=True).start()
            await lire_jusqua(ws, recus, "telemetry")

        self.dialogue(scenario, duree=4)

    def test_abonnement_oublie_a_la_deconnexion(self):
        serveur = self.lance()

        async def scenario(ws, recus):
            await lire(ws, recus)
            await ws.send(json.dumps({"subscribe": ["speed"]}))
            await lire_jusqua(ws, recus, "subscribed")

        self.dialogue(scenario)
        deadline = time.monotonic() + 3
        while serveur._subscriptions and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(serveur._subscriptions), 0)


class TestTrameEtat(ServeurTestCase):
    def test_emise_periodiquement(self):
        self.lance(status_interval=0.2)

        async def scenario(ws, recus):
            await lire(ws, recus)  # hello
            etat = await lire_jusqua(ws, recus, "status")
            self.assertIn("receiving", etat)
            self.assertIn("clients", etat)

        self.dialogue(scenario)

    def test_receiving_faux_sans_paquet(self):
        """Aucun publish() n'a jamais eu lieu : le jeu n'envoie rien."""
        self.lance(status_interval=0.2, stale_after=0.5)

        async def scenario(ws, recus):
            await lire(ws, recus)
            etat = await lire_jusqua(ws, recus, "status")
            self.assertFalse(etat["receiving"])

        self.dialogue(scenario)

    def test_receiving_vrai_meme_si_rien_ne_change(self):
        """Distinction essentielle : des paquets qui arrivent sans faire varier
        aucune valeur (menu, voiture a l'arret) ne sont PAS un flux mort.
        C'est pourquoi publish() horodate avant toute sortie anticipee.
        """
        serveur = self.lance(status_interval=0.2, stale_after=1.0,
                             rate_hz=1000, differential=True)
        arret = threading.Event()

        def produire():
            while not arret.is_set():
                serveur.publish({"constante": 1.0})  # jamais de variation
                time.sleep(0.02)

        threading.Thread(target=produire, daemon=True).start()
        self.addCleanup(arret.set)

        async def scenario(ws, recus):
            await lire(ws, recus)
            etat = await lire_jusqua(ws, recus, "status")
            self.assertTrue(etat["receiving"], "flux statique pris pour un flux mort")

        self.dialogue(scenario)

    def test_complement_fourni_par_le_pont(self):
        serveur = self.lance(status_interval=0.2)
        serveur.status_factory = lambda: {"packets": 1234, "car_name": "Ferrari J50"}

        async def scenario(ws, recus):
            await lire(ws, recus)
            etat = await lire_jusqua(ws, recus, "status")
            self.assertEqual(etat["packets"], 1234)
            self.assertEqual(etat["car_name"], "Ferrari J50")

        self.dialogue(scenario)

    def test_fabrique_defaillante_ne_casse_pas_l_etat(self):
        serveur = self.lance(status_interval=0.2)

        def casse():
            raise ValueError("boum")

        serveur.status_factory = casse

        async def scenario(ws, recus):
            await lire(ws, recus)
            etat = await lire_jusqua(ws, recus, "status")
            self.assertIn("receiving", etat)

        self.dialogue(scenario)


if __name__ == "__main__":
    unittest.main()
