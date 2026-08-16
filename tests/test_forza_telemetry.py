"""Decodage du paquet Forza."""

import unittest

from forza_telemetry import HORIZON_DASH_SIZE, SLED_SIZE, parse
from tests.helpers import make_packet


class TestTaillesAcceptees(unittest.TestCase):
    """Le controle de taille doit etre strict.

    Un `>=` laissait passer n'importe quel datagramme etranger de 323 octets
    ou plus (bavardage reseau, autre jeu) et le decodait en flottants
    aberrants, aussitot diffuses en OSC et en WebSocket.
    """

    def test_tailles_valides(self):
        for taille in (SLED_SIZE, HORIZON_DASH_SIZE, HORIZON_DASH_SIZE + 1):
            with self.subTest(taille=taille):
                self.assertIsNotNone(parse(bytes(taille)))

    def test_tailles_refusees(self):
        for taille in (0, 60, 231, 233, 322, 325, 400, 1200, 1500):
            with self.subTest(taille=taille):
                self.assertIsNone(parse(bytes(taille)))


class TestDecodage(unittest.TestCase):
    def test_nombre_de_champs(self):
        frame = parse(make_packet())
        self.assertEqual(len(frame.values), 88)

    def test_valeurs_relues(self):
        packet = make_packet(
            speed=55.5, current_engine_rpm=6200.0, engine_max_rpm=7800.0,
            gear=4, accel=200, brake=10, steer=-60,
            car_ordinal=3917, car_class=4, car_performance_index=769,
            drivetrain_type=1, num_cylinders=10,
        )
        v = parse(packet).values
        self.assertAlmostEqual(v["speed"], 55.5, places=3)
        self.assertAlmostEqual(v["current_engine_rpm"], 6200.0, places=1)
        self.assertEqual(v["gear"], 4)
        self.assertEqual(v["accel"], 200)
        self.assertEqual(v["steer"], -60)
        self.assertEqual(v["car_ordinal"], 3917)
        self.assertEqual(v["num_cylinders"], 10)

    def test_is_race_on(self):
        self.assertTrue(parse(make_packet(is_race_on=1)).is_race_on)
        self.assertFalse(parse(make_packet(is_race_on=0)).is_race_on)

    def test_champs_horizon_apres_le_sled(self):
        """Les 12 octets d'extras Horizon se placent entre le sled et le dash.

        Si l'ordre etait faux, position_x et les suivants seraient decales.
        """
        v = parse(make_packet(position_x=123.5, position_y=4.25, position_z=-67.0)).values
        self.assertAlmostEqual(v["position_x"], 123.5, places=3)
        self.assertAlmostEqual(v["position_y"], 4.25, places=3)
        self.assertAlmostEqual(v["position_z"], -67.0, places=3)


if __name__ == "__main__":
    unittest.main()
