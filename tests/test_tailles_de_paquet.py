"""Tailles de paquet : usure des pneus, et refus qui se voient.

Deux defauts jumeaux, decouverts en lisant un parseur FH6 independant
(TheBanHammer/fh6-tel) : le jeu peut publier l'usure des quatre pneus, ce qui
porte le paquet a 339 octets, et notre decodeur refusait toute taille inconnue
en silence. L'interface annoncait alors "No packets from the game" alors que
les paquets arrivaient — diagnostic faux, cause invisible.

Le garde-fou de taille reste STRICT (un `>=` decodait n'importe quel
datagramme etranger en flottants aberrants diffuses aussitot en OSC) ; c'est le
refus qui devient visible.
"""

import socket
import struct
import unittest

import forza_telemetry
from bridge import Bridge
from forza_telemetry import (ACCEPTED_SIZES, HORIZON_DASH_SIZE,
                             HORIZON_WEAR_SIZE, SLED_SIZE, TIRE_WEAR_CHANNELS,
                             parse)
from tests.helpers import OscRecorder, free_port, make_packet, wait_until


def paquet_avec_usure(usures=(0.10, 0.20, 0.30, 0.40), queue=False) -> bytes:
    """Paquet dash complet suivi des quatre flottants d'usure."""
    base = make_packet(speed=30.0, gear=3)[:HORIZON_DASH_SIZE]
    packet = base + struct.pack("<ffff", *usures)
    return packet + b"\x00" if queue else packet


class TestTaillesAcceptees(unittest.TestCase):
    def test_liste_des_tailles(self):
        self.assertEqual(sorted(ACCEPTED_SIZES), [232, 323, 324, 339, 340])

    def test_usure_decodee_a_339(self):
        trame = parse(paquet_avec_usure())
        self.assertIsNotNone(trame, "un paquet de 339 octets doit etre lu")
        for canal, attendu in zip(TIRE_WEAR_CHANNELS, (0.10, 0.20, 0.30, 0.40)):
            with self.subTest(canal=canal):
                self.assertAlmostEqual(trame.values[canal], attendu, places=5)

    def test_usure_decodee_a_340(self):
        """Le jeu ajoute parfois un octet de fin : mesure a 324 sur la variante
        courte, donc la variante longue doit tolerer la meme chose."""
        trame = parse(paquet_avec_usure(queue=True))
        self.assertIsNotNone(trame)
        self.assertAlmostEqual(trame.values["tire_wear_rr"], 0.40, places=5)

    def test_le_reste_du_paquet_reste_juste(self):
        """Contre-epreuve : ajouter des champs ne doit pas decaler les autres."""
        court = parse(make_packet(speed=30.0, gear=3))
        long = parse(paquet_avec_usure())
        for canal in ("speed", "gear", "accel", "steer", "current_engine_rpm",
                      "is_race_on", "car_ordinal"):
            with self.subTest(canal=canal):
                self.assertEqual(long.values[canal], court.values[canal])

    def test_usure_absente_des_paquets_courts(self):
        """Aucune valeur inventee : le flux mesure (324 octets) ne porte pas
        ces champs."""
        trame = parse(make_packet(speed=30.0))
        for canal in TIRE_WEAR_CHANNELS:
            with self.subTest(canal=canal):
                self.assertNotIn(canal, trame.values)

    def test_tailles_intermediaires_refusees(self):
        """Le parseur independant lit l'usure champ par champ des 327 octets.
        Nous ne l'imitons pas : une taille partielle n'est pas mesuree, donc
        elle est refusee — et comptee, ce qui la rend visible."""
        for taille in (325, 327, 331, 335, 338, 341, 400):
            with self.subTest(taille=taille):
                self.assertIsNone(parse(b"\x00" * taille))

    def test_tailles_connues_toujours_lues(self):
        for taille in (SLED_SIZE, HORIZON_DASH_SIZE, HORIZON_DASH_SIZE + 1,
                       HORIZON_WEAR_SIZE, HORIZON_WEAR_SIZE + 1):
            with self.subTest(taille=taille):
                self.assertIsNotNone(parse(b"\x00" * taille))

    def test_usure_publiee_dans_le_catalogue(self):
        from channel_catalog import CATEGORY_OF, RAW_CHANNELS, UNITS
        for canal in TIRE_WEAR_CHANNELS:
            with self.subTest(canal=canal):
                self.assertIn(canal, RAW_CHANNELS)
                self.assertIn(canal, UNITS)
                self.assertEqual(CATEGORY_OF[canal], "Tyres")


def envoie(port: int, packet: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
    finally:
        sock.close()


class TestRefusComptes(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.recorder = OscRecorder()
        self.bridge = Bridge(listen_port=self.port,
                             osc_clients=[self.recorder],
                             selected_channels=frozenset({"speed"}))
        self.bridge.start()
        self.assertTrue(self.bridge.bound.wait(5))
        self.assertIsNone(self.bridge.error)

    def tearDown(self):
        self.bridge.stop()
        self.bridge.join(timeout=3)

    def test_compteur_a_zero_au_depart(self):
        self.assertEqual(self.bridge.rejected_count, 0)
        self.assertIsNone(self.bridge.rejected_summary())

    def test_paquet_de_taille_inconnue_compte(self):
        for _ in range(3):
            envoie(self.port, b"\x00" * 500)
        wait_until(lambda: self.bridge.rejected_count >= 3)

        self.assertEqual(self.bridge.rejected_count, 3)
        self.assertEqual(self.bridge.rejected_sizes, {500: 3})
        self.assertEqual(self.bridge.packet_count, 0,
                         "un paquet refuse ne doit pas etre compte comme recu")

    def test_resume_nomme_la_taille(self):
        """C'est la taille qui permet de comprendre : sans elle, le message ne
        vaut pas mieux que le silence."""
        envoie(self.port, b"\x00" * 331)
        wait_until(lambda: self.bridge.rejected_count >= 1)

        resume = self.bridge.rejected_summary()
        self.assertIn("331", resume)
        self.assertIn("339", resume, "les tailles attendues doivent etre citees")

    def test_plusieurs_tailles_distinguees(self):
        envoie(self.port, b"\x00" * 100)
        envoie(self.port, b"\x00" * 100)
        envoie(self.port, b"\x00" * 700)
        wait_until(lambda: self.bridge.rejected_count >= 3)
        self.assertEqual(self.bridge.rejected_sizes, {100: 2, 700: 1})

    def test_paquet_valide_ne_compte_pas(self):
        """Contre-epreuve : sans elle, un compteur incremente a chaque paquet
        passerait tous les tests ci-dessus."""
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: self.bridge.packet_count >= 1)
        self.assertEqual(self.bridge.rejected_count, 0)
        self.assertIsNone(self.bridge.rejected_summary())

    def test_usure_emise_en_osc(self):
        """Chemin complet : un paquet de 339 octets doit sortir en OSC."""
        self.bridge.selected_channels = frozenset({"speed", "tire_wear_fl"})
        envoie(self.port, paquet_avec_usure())
        wait_until(lambda: any(a == "/forza/tire_wear_fl"
                               for a, _ in self.recorder.messages))

        recus = [v for a, v in self.recorder.messages
                 if a == "/forza/tire_wear_fl"]
        self.assertTrue(recus, "usure non diffusee")
        self.assertAlmostEqual(recus[-1], 0.10, places=5)

    def test_trame_d_etat_signale_les_refus(self):
        envoie(self.port, b"\x00" * 500)
        wait_until(lambda: self.bridge.rejected_count >= 1)
        etat = self.bridge.status()
        self.assertEqual(etat["rejected"], 1)
        self.assertEqual(etat["rejected_sizes"], {500: 1})

    def test_trame_d_etat_muette_sans_refus(self):
        """Un client n'a pas a filtrer des zeros pour savoir que tout va
        bien."""
        etat = self.bridge.status()
        self.assertNotIn("rejected", etat)
        self.assertNotIn("rejected_sizes", etat)


class TestMelangeDeTailles(unittest.TestCase):
    """Un flux qui change de variante en cours de route ne doit ni perdre les
    paquets lisibles ni masquer les autres."""

    def setUp(self):
        self.port = free_port()
        self.recorder = OscRecorder()
        self.bridge = Bridge(listen_port=self.port,
                             osc_clients=[self.recorder],
                             selected_channels=frozenset({"speed"}))
        self.bridge.start()
        self.assertTrue(self.bridge.bound.wait(5))

    def tearDown(self):
        self.bridge.stop()
        self.bridge.join(timeout=3)

    def test_les_deux_comptes_avancent_separement(self):
        envoie(self.port, make_packet(speed=10.0))
        envoie(self.port, b"\x00" * 999)
        envoie(self.port, paquet_avec_usure())
        wait_until(lambda: self.bridge.packet_count >= 2
                   and self.bridge.rejected_count >= 1)

        self.assertEqual(self.bridge.packet_count, 2)
        self.assertEqual(self.bridge.rejected_count, 1)
        self.assertTrue(self.bridge.is_alive(),
                        f"thread mort: {self.bridge.error}")


if __name__ == "__main__":
    unittest.main()
