"""Boucle de reception partagee (bridge.Bridge)."""

import random
import socket
import threading
import unittest

from bridge import Bridge, _osc_safe
from channel_catalog import ALL_CHANNELS, RAW_CHANNELS
from tests.helpers import OscRecorder, free_port, make_packet, wait_until


def envoie(port: int, packet: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
    finally:
        sock.close()


class TestOscSafe(unittest.TestCase):
    """python-osc bascule sur l'etiquette int64 au-dela de 2^31, que l'OSC In
    CHOP de TouchDesigner ne decode pas de facon fiable : le canal disparait
    sans erreur. `timestamp_ms` franchit ce seuil apres ~24,8 jours."""

    def test_entiers_dans_int32_inchanges(self):
        for valeur in (0, -1, 100, 2 ** 31 - 1, -(2 ** 31)):
            with self.subTest(valeur=valeur):
                self.assertIsInstance(_osc_safe(valeur), int)

    def test_entiers_hors_int32_convertis(self):
        for valeur in (2 ** 31, 4294967295, -(2 ** 31) - 1):
            with self.subTest(valeur=valeur):
                self.assertIsInstance(_osc_safe(valeur), float)

    def test_flottants_inchanges(self):
        self.assertEqual(_osc_safe(3.5), 3.5)


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.recorder = OscRecorder()
        self.bridge = None

    def tearDown(self):
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge.join(timeout=3)

    def demarre(self, **kwargs) -> Bridge:
        self.bridge = Bridge(listen_port=self.port,
                             osc_clients=[self.recorder], **kwargs)
        self.bridge.start()
        self.assertTrue(self.bridge.bound.wait(5), "bind jamais tente")
        self.assertIsNone(self.bridge.error)
        return self.bridge


class TestEmission(BridgeTestCase):
    def test_seuls_les_canaux_selectionnes_partent(self):
        self.demarre(selected_channels=frozenset({"speed", "gear"}))
        envoie(self.port, make_packet(speed=30.0, gear=3))
        wait_until(lambda: self.bridge.packet_count >= 1)
        wait_until(lambda: len(self.recorder.messages) >= 2)

        mesures = {a for a in self.recorder.addresses if a != "/forza/car_name"}
        self.assertEqual(mesures, {"/forza/speed", "/forza/gear"})

    def test_selection_none_envoie_tout(self):
        """Canaux bruts ET derives, ces derniers etant calcules par le pont."""
        self.demarre(selected_channels=None)
        envoie(self.port, make_packet(speed=30.0))
        attendu = len(ALL_CHANNELS)
        wait_until(lambda: len(self.recorder.addresses) >= attendu)
        mesures = {a for a in self.recorder.addresses if a != "/forza/car_name"}
        self.assertEqual(len(mesures), attendu)
        self.assertIn("/forza/speed_kmh", mesures)

    def test_derives_desactivables(self):
        self.demarre(selected_channels=None, derived=False)
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: len(self.recorder.addresses) >= len(RAW_CHANNELS))
        mesures = {a for a in self.recorder.addresses if a != "/forza/car_name"}
        self.assertEqual(len(mesures), len(RAW_CHANNELS))
        self.assertNotIn("/forza/speed_kmh", mesures)

    def test_nom_de_vehicule_emis_une_seule_fois(self):
        """Chaine envoyee au changement de voiture seulement, pas 60 fois/s."""
        self.demarre(selected_channels=frozenset({"speed"}))
        for _ in range(5):
            envoie(self.port, make_packet(speed=10.0, car_ordinal=292))
        wait_until(lambda: self.bridge.packet_count >= 5)

        noms = [v for a, v in self.recorder.messages if a == "/forza/car_name"]
        self.assertEqual(noms, ["2003 Porsche Carrera GT"])

    def test_nom_reemis_au_changement(self):
        self.demarre(selected_channels=frozenset({"speed"}))
        envoie(self.port, make_packet(car_ordinal=292))
        wait_until(lambda: self.bridge.packet_count >= 1)
        envoie(self.port, make_packet(car_ordinal=249))
        wait_until(lambda: self.bridge.packet_count >= 2)

        noms = [v for a, v in self.recorder.messages if a == "/forza/car_name"]
        self.assertEqual(noms, ["2003 Porsche Carrera GT", "1964 Ferrari 250 GTO"])

    def test_only_racing_filtre(self):
        self.demarre(selected_channels=frozenset({"speed"}), only_racing=True)
        envoie(self.port, make_packet(is_race_on=0, speed=30.0))
        self.assertFalse(wait_until(lambda: self.bridge.packet_count >= 1, timeout=1))
        envoie(self.port, make_packet(is_race_on=1, speed=30.0))
        self.assertTrue(wait_until(lambda: self.bridge.packet_count >= 1))


class TestRobustesse(BridgeTestCase):
    def test_selection_modifiable_pendant_la_reception(self):
        """Defaut corrige : muter en place l'ensemble partage avec le thread
        levait "Set changed size during iteration" et tuait ce thread en
        silence — cocher une case pendant la reception suffisait.
        """
        self.demarre(selected_channels=frozenset({"speed"}))
        arret = threading.Event()

        def emetteur():
            while not arret.is_set():
                envoie(self.port, make_packet(speed=42.0))

        def modificateur():
            while not arret.is_set():
                taille = random.randint(0, len(ALL_CHANNELS))
                self.bridge.selected_channels = frozenset(
                    random.sample(ALL_CHANNELS, taille))

        threads = [threading.Thread(target=emetteur, daemon=True),
                   threading.Thread(target=modificateur, daemon=True)]
        for t in threads:
            t.start()
        wait_until(lambda: self.bridge.packet_count >= 50, timeout=5)
        arret.set()
        for t in threads:
            t.join(timeout=2)

        self.assertTrue(self.bridge.is_alive(), f"thread mort: {self.bridge.error}")
        self.assertIsNone(self.bridge.error)

    def test_bind_impossible_remonte_une_erreur(self):
        occupant = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        occupant.bind(("0.0.0.0", self.port))
        try:
            bridge = Bridge(listen_port=self.port, osc_clients=[self.recorder])
            bridge.start()
            self.assertTrue(bridge.bound.wait(5), "evenement 'bound' jamais arme")
            bridge.join(timeout=3)
            self.assertIsNotNone(bridge.error)
            self.assertFalse(bridge.is_alive())
        finally:
            occupant.close()

    def test_panne_en_cours_de_route_est_visible(self):
        """Sans capture, une exception tuait le thread en silence et
        l'interface continuait d'afficher "En ecoute"."""
        self.demarre(selected_channels=frozenset({"speed"}))

        class ClientCasse:
            def send(self, *args):
                raise RuntimeError("panne simulee")

        self.bridge.osc_clients = [ClientCasse()]
        envoie(self.port, make_packet(speed=10.0))
        self.assertTrue(wait_until(lambda: not self.bridge.is_alive()))
        self.assertIn("panne simulee", self.bridge.error)


class TestLissage(BridgeTestCase):
    """Le lissage doit etre reellement branche dans la boucle : une mutation
    qui le debranchait n'etait detectee par aucun test."""

    def test_canal_lisse_emis_en_plus_du_brut(self):
        self.demarre(selected_channels=frozenset({"speed_kmh"}),
                     smoothing_settings={"speed_kmh": 0.2})
        for _ in range(3):
            envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: self.bridge.packet_count >= 3)
        wait_until(lambda: "/forza/speed_kmh_smooth" in self.recorder.addresses)

        self.assertIn("/forza/speed_kmh", self.recorder.addresses)
        self.assertIn("/forza/speed_kmh_smooth", self.recorder.addresses)

    def test_valeur_brute_intacte_malgre_le_lissage(self):
        """Garantie de non-alteration, verifiee de bout en bout."""
        self.demarre(selected_channels=frozenset({"speed_kmh"}),
                     smoothing_settings={"speed_kmh": 1.0})
        envoie(self.port, make_packet(speed=0.0))
        wait_until(lambda: self.bridge.packet_count >= 1)
        envoie(self.port, make_packet(speed=50.0))
        wait_until(lambda: self.bridge.packet_count >= 2)

        bruts = [v for a, v in self.recorder.messages if a == "/forza/speed_kmh"]
        self.assertAlmostEqual(bruts[-1], 180.0, places=3)  # 50 m/s = 180 km/h

    def test_sans_reglage_aucun_canal_lisse(self):
        self.demarre(selected_channels=frozenset({"speed_kmh"}))
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: "/forza/speed_kmh" in self.recorder.addresses)
        self.assertNotIn("/forza/speed_kmh_smooth", self.recorder.addresses)

    def test_annonce_dans_l_accueil(self):
        self.demarre(selected_channels=frozenset({"speed_kmh"}),
                     smoothing_settings={"speed_kmh": 0.2})
        hello = self.bridge.hello()
        self.assertIn("speed_kmh_smooth", hello["channels"])
        self.assertEqual(hello["units"]["speed_kmh_smooth"], "km/h",
                         "le lisse herite de l'unite de sa source")

    def test_changement_de_vehicule_reinitialise_le_filtre(self):
        """Sinon la sortie glisserait depuis les valeurs de l'ancienne voiture."""
        self.demarre(selected_channels=frozenset({"speed_kmh"}),
                     smoothing_settings={"speed_kmh": 5.0})
        envoie(self.port, make_packet(speed=60.0, car_ordinal=292))
        wait_until(lambda: self.bridge.packet_count >= 1)
        envoie(self.port, make_packet(speed=0.0, car_ordinal=249))
        wait_until(lambda: self.bridge.packet_count >= 2)

        lisses = [v for a, v in self.recorder.messages
                  if a == "/forza/speed_kmh_smooth"]
        self.assertEqual(lisses[-1], 0.0)


class TestHello(BridgeTestCase):
    def test_contenu(self):
        self.demarre(selected_channels=frozenset({"speed", "gear"}))
        hello = self.bridge.hello()
        self.assertIn("speed", hello["channels"])
        self.assertIn("engine_max_rpm", hello["channels"],
                      "champ de contexte toujours joint")
        self.assertEqual(hello["units"]["speed"], "m/s")
        self.assertEqual(hello["categories"]["gear"], "Commandes")

    def test_selection_none_annonce_tout(self):
        self.demarre(selected_channels=None)
        self.assertEqual(len(self.bridge.hello()["channels"]), len(ALL_CHANNELS))


if __name__ == "__main__":
    unittest.main()
