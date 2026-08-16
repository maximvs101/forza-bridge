"""Serveur WebSocket : assainissement, cadence, differentiel."""

import asyncio
import json
import math
import threading
import time
import unittest

import websockets

from tests.helpers import free_port, wait_until
from ws_server import (_MISSING, TelemetryWebSocketServer, _changed,
                       _json_safe)
import socket as _socket


def port_tcp() -> int:
    return free_port(_socket.SOCK_STREAM)


class TestJsonSafe(unittest.TestCase):
    """NaN et Infinity ne sont pas du JSON valide : `JSON.parse` les rejette
    et la trame est perdue en silence cote navigateur."""

    def test_non_finis_remplaces(self):
        propre = _json_safe({"a": float("nan"), "b": float("inf"),
                             "c": float("-inf"), "d": 1.5, "e": 3})
        self.assertIsNone(propre["a"])
        self.assertIsNone(propre["b"])
        self.assertIsNone(propre["c"])
        self.assertEqual(propre["d"], 1.5)

    def test_serialisable_en_json_strict(self):
        texte = json.dumps(_json_safe({"a": float("nan")}), allow_nan=False)
        self.assertNotIn("NaN", texte)
        self.assertEqual(json.loads(texte), {"a": None})


class TestChanged(unittest.TestCase):
    def test_champ_absent(self):
        self.assertTrue(_changed(_MISSING, 1.0, 1e-4))

    def test_seuil_flottant(self):
        self.assertFalse(_changed(1.0, 1.0 + 1e-6, 1e-4))
        self.assertTrue(_changed(1.0, 1.0 + 1e-2, 1e-4))

    def test_types_non_flottants_compares_strictement(self):
        self.assertFalse(_changed(3, 3, 1e-4))
        self.assertTrue(_changed(3, 4, 1e-4))
        self.assertFalse(_changed("Ferrari", "Ferrari", 1e-4))
        self.assertTrue(_changed("Ferrari", "Porsche", 1e-4))


class TestDemarrage(unittest.TestCase):
    def test_port_invalide_signale(self):
        """`except OSError` seul laissait passer OverflowError : start()
        renvoyait True alors que rien n'ecoutait."""
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=99999)
        try:
            self.assertFalse(serveur.start())
            self.assertIsNotNone(serveur.error)
        finally:
            serveur.stop()

    def test_port_valide(self):
        serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp())
        try:
            self.assertTrue(serveur.start())
            self.assertIsNone(serveur.error)
        finally:
            serveur.stop()

    def test_ecoute_locale_par_defaut(self):
        """Le flux contient la position du vehicule : pas d'exposition reseau
        sans demande explicite."""
        self.assertEqual(TelemetryWebSocketServer().host, "127.0.0.1")


class ServeurTestCase(unittest.TestCase):
    """Base : un serveur et un client WebSocket sur un port libre."""

    def lance(self, **kwargs) -> TelemetryWebSocketServer:
        self.serveur = TelemetryWebSocketServer(host="127.0.0.1", port=port_tcp(),
                                                serve_assets=False, **kwargs)
        self.assertTrue(self.serveur.start())
        self.addCleanup(self.serveur.stop)
        return self.serveur

    def collecte(self, duree: float, producteur=None) -> list[dict]:
        """Connecte un client, lance le producteur, renvoie les messages."""
        recus: list[dict] = []
        connecte = threading.Event()

        async def client():
            url = f"ws://127.0.0.1:{self.serveur.port}"
            async with websockets.connect(url) as ws:
                connecte.set()
                fin = time.monotonic() + duree
                while time.monotonic() < fin:
                    try:
                        reste = fin - time.monotonic()
                        recus.append(json.loads(
                            await asyncio.wait_for(ws.recv(), timeout=max(0.05, reste))))
                    except asyncio.TimeoutError:
                        break

        if producteur is not None:
            def lancer():
                connecte.wait(5)
                time.sleep(0.1)
                producteur()
            threading.Thread(target=lancer, daemon=True).start()

        asyncio.run(client())
        return recus


class TestAccueil(ServeurTestCase):
    def test_premier_message(self):
        self.lance(rate_hz=60)
        messages = self.collecte(1.0)
        self.assertTrue(messages)
        hello = messages[0]
        self.assertEqual(hello["type"], "hello")
        self.assertEqual(hello["rate_hz"], 60)
        self.assertTrue(hello["differential"])

    def test_schema_fourni_par_le_pont(self):
        serveur = self.lance()
        serveur.hello_factory = lambda: {"channels": ["speed"], "units": {"speed": "m/s"}}
        hello = self.collecte(1.0)[0]
        self.assertEqual(hello["channels"], ["speed"])
        self.assertEqual(hello["units"]["speed"], "m/s")

    def test_fabrique_defaillante_ne_casse_pas_l_accueil(self):
        serveur = self.lance()

        def casse():
            raise ValueError("boum")

        serveur.hello_factory = casse
        hello = self.collecte(1.0)[0]
        self.assertEqual(hello["type"], "hello")

    def test_etat_courant_envoye_a_la_connexion(self):
        """Sans cela, un client connecte a l'arret reste vide jusqu'a la
        reprise du flux, et en differentiel il n'a aucune base de fusion."""
        serveur = self.lance()
        serveur._state = {"speed": 12.0, "gear": 2}
        messages = self.collecte(1.0)
        self.assertEqual(messages[0]["type"], "hello")
        self.assertEqual(messages[1]["type"], "telemetry")
        self.assertTrue(messages[1]["full"])
        self.assertEqual(messages[1]["speed"], 12.0)


class TestCadence(ServeurTestCase):
    def test_plafond_respecte(self):
        """Une limitation "temps ecoule depuis le dernier envoi" derive : avec
        une source a 60 Hz elle donnait 20-24 Hz pour un plafond a 30."""
        for cible in (30, 60):
            with self.subTest(plafond=cible):
                self.lance(rate_hz=cible, differential=False)

                def produire():
                    fin = time.time() + 2.0
                    i = 0
                    while time.time() < fin:
                        self.serveur.publish({"v": float(i)})
                        i += 1
                        time.sleep(1 / 250)

                messages = self.collecte(2.2, produire)
                telem = [m for m in messages if m.get("type") == "telemetry"]
                mesure = len(telem) / 2.0
                self.assertGreater(mesure, cible * 0.8, f"{mesure:.1f} Hz")
                self.assertLess(mesure, cible * 1.2, f"{mesure:.1f} Hz")
                self.serveur.stop()

    def test_source_60hz_plafond_30hz(self):
        """Reproduit le defaut d'origine, que le test a 250 Hz ne voyait pas.

        La derive n'apparait que si la periode de la source est une fraction
        notable de l'intervalle vise : a 60 Hz avec un plafond a 30 Hz,
        l'echeance calculee depuis l'instant d'envoi tombe juste apres le
        paquet suivant, une trame sur deux saute, et on mesure 20 Hz.
        """
        self.lance(rate_hz=30, differential=False)
        duree = 2.0

        def produire():
            periode = 1.0 / 60
            prochaine = time.monotonic()
            fin = time.monotonic() + duree
            i = 0
            while time.monotonic() < fin:
                self.serveur.publish({"v": float(i)})
                i += 1
                prochaine += periode
                delai = prochaine - time.monotonic()
                if delai > 0:
                    time.sleep(delai)

        messages = self.collecte(duree + 0.3, produire)
        telem = [m for m in messages if m.get("type") == "telemetry"]
        mesure = len(telem) / duree
        # Correct : ~30 Hz. Version derivante : ~20 Hz.
        self.assertGreater(mesure, 26.0,
                           f"{mesure:.1f} Hz — la limitation derive")

    def test_fabrique_appelee_seulement_a_l_emission(self):
        """La charge utile ne doit pas etre construite pour des trames que le
        plafond va jeter."""
        self.lance(rate_hz=20, differential=False)
        appels = {"n": 0}

        def fabrique():
            appels["n"] += 1
            return {"v": 1.0}

        def produire():
            fin = time.time() + 1.0
            while time.time() < fin:
                self.serveur.publish(fabrique)
                time.sleep(1 / 200)

        messages = self.collecte(1.2, produire)
        telem = [m for m in messages if m.get("type") == "telemetry"]
        self.assertEqual(appels["n"], len(telem))
        self.assertLess(appels["n"], 40, "la fabrique suit les envois, pas les appels")


class TestDifferentiel(ServeurTestCase):
    def test_invariant_etat_client_egale_etat_serveur(self):
        """Seul controle qui prouve qu'un client differentiel ne derive pas.

        Ne PAS comparer l'etat reconstruit a une trame complete recue plus
        tard : elle provient d'un echantillon posterieur, les ecarts sont
        alors normaux et le test ne prouve rien.
        """
        self.lance(rate_hz=1000, differential=True, epsilon=1e-4, resync_seconds=0.5)

        def produire():
            for i in range(60):
                self.serveur.publish({
                    "statique": 42,
                    "texte": "Ferrari J50",
                    "rapide": float(i),
                    "microscopique": 1.0 + i * 1e-6,   # sous le seuil
                    "palier": float(i // 7),           # non aligne sur la resynchro
                })
                time.sleep(0.02)

        messages = self.collecte(1.8, produire)
        telem = [m for m in messages if m.get("type") == "telemetry"]
        self.assertTrue(telem)

        etat = {}
        for message in telem:
            valeurs = {k: v for k, v in message.items() if k not in ("type", "full")}
            if message.get("full"):
                etat = valeurs
            else:
                etat.update(valeurs)

        self.assertEqual(etat, self.serveur._state)

    def test_champs_statiques_absents_des_trames_partielles(self):
        self.lance(rate_hz=1000, differential=True, resync_seconds=10)

        def produire():
            for i in range(30):
                self.serveur.publish({"statique": 42, "rapide": float(i)})
                time.sleep(0.02)

        messages = self.collecte(1.0, produire)
        partielles = [m for m in messages
                      if m.get("type") == "telemetry" and not m.get("full")]
        self.assertTrue(partielles)
        self.assertFalse(any("statique" in m for m in partielles))
        self.assertTrue(all("rapide" in m for m in partielles))

    def test_variation_sous_le_seuil_supprimee(self):
        self.lance(rate_hz=1000, differential=True, epsilon=1e-3, resync_seconds=10)

        def produire():
            for i in range(30):
                self.serveur.publish({"ancre": float(i), "micro": 1.0 + i * 1e-6})
                time.sleep(0.02)

        messages = self.collecte(1.0, produire)
        partielles = [m for m in messages
                      if m.get("type") == "telemetry" and not m.get("full")]
        self.assertFalse(any("micro" in m for m in partielles))

    def test_resynchronisation_periodique(self):
        """Indispensable, pas cosmetique : une trame peut etre abandonnee pour
        un client lent, et sans renvoi complet ce client resterait faux."""
        self.lance(rate_hz=1000, differential=True, resync_seconds=0.3)

        def produire():
            for i in range(60):
                self.serveur.publish({"v": float(i)})
                time.sleep(0.02)

        messages = self.collecte(1.5, produire)
        pleines = [m for m in messages
                   if m.get("type") == "telemetry" and m.get("full")]
        self.assertGreaterEqual(len(pleines), 3)

    def test_mode_complet_desactive_le_differentiel(self):
        self.lance(rate_hz=1000, differential=False, resync_seconds=10)

        def produire():
            for i in range(20):
                self.serveur.publish({"statique": 42, "rapide": float(i)})
                time.sleep(0.02)

        messages = self.collecte(1.0, produire)
        telem = [m for m in messages if m.get("type") == "telemetry"]
        self.assertTrue(all("statique" in m for m in telem))


class TestClients(ServeurTestCase):
    def test_deconnexion_nettoie(self):
        self.lance()
        self.collecte(0.5)
        self.assertTrue(wait_until(lambda: self.serveur.client_count == 0))

    def test_publish_sans_client_ne_fait_rien(self):
        self.lance()
        self.assertFalse(self.serveur.publish({"v": 1.0}))


if __name__ == "__main__":
    unittest.main()
