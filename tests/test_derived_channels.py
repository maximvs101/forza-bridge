"""Canaux derives : formules, bornes et tolerance aux donnees incompletes."""

import math
import unittest

from channel_catalog import UNITS
from derived_channels import DERIVED_CHANNELS, DERIVED_UNITS, compute


class TestConversions(unittest.TestCase):
    def test_vitesse(self):
        d = compute({"speed": 10.0})
        self.assertAlmostEqual(d["speed_kmh"], 36.0, places=6)
        self.assertAlmostEqual(d["speed_mph"], 22.36936, places=4)

    def test_pedales_ramenees_a_0_1(self):
        d = compute({"accel": 255, "brake": 0, "clutch": 128, "hand_brake": 255})
        self.assertEqual(d["throttle"], 1.0)
        self.assertEqual(d["brake_pedal"], 0.0)
        self.assertAlmostEqual(d["clutch_pedal"], 128 / 255, places=6)
        self.assertEqual(d["handbrake_pedal"], 1.0)

    def test_volant_signe(self):
        self.assertEqual(compute({"steer": 127})["steer_norm"], 1.0)
        self.assertEqual(compute({"steer": -127})["steer_norm"], -1.0)
        self.assertEqual(compute({"steer": 0})["steer_norm"], 0.0)

    def test_volant_borne_a_moins_un(self):
        """L'octet signe descend a -128 : sans bornage le canal sortirait
        de la plage annoncee."""
        self.assertEqual(compute({"steer": -128})["steer_norm"], -1.0)

    def test_forces_g(self):
        d = compute({"acceleration_x": 9.80665, "acceleration_y": -19.6133,
                     "acceleration_z": 0.0})
        self.assertAlmostEqual(d["g_lateral"], 1.0, places=6)
        self.assertAlmostEqual(d["g_vertical"], -2.0, places=4)
        self.assertAlmostEqual(d["g_longitudinal"], 0.0, places=6)

    def test_angles_en_degres(self):
        d = compute({"yaw": math.pi, "pitch": math.pi / 2, "roll": 0.0})
        self.assertAlmostEqual(d["yaw_deg"], 180.0, places=6)
        self.assertAlmostEqual(d["pitch_deg"], 90.0, places=6)
        self.assertAlmostEqual(d["roll_deg"], 0.0, places=6)

    def test_temperatures_en_celsius(self):
        d = compute({"tire_temp_fl": 32.0, "tire_temp_fr": 212.0,
                     "tire_temp_rl": 98.6, "tire_temp_rr": -40.0})
        self.assertAlmostEqual(d["tire_temp_fl_c"], 0.0, places=6)
        self.assertAlmostEqual(d["tire_temp_fr_c"], 100.0, places=6)
        self.assertAlmostEqual(d["tire_temp_rl_c"], 37.0, places=4)
        self.assertAlmostEqual(d["tire_temp_rr_c"], -40.0, places=6)


class TestRegime(unittest.TestCase):
    def test_rapport_de_regime(self):
        d = compute({"current_engine_rpm": 3900.0, "engine_max_rpm": 7800.0})
        self.assertAlmostEqual(d["rpm_ratio"], 0.5, places=6)

    def test_borne_a_un(self):
        d = compute({"current_engine_rpm": 9000.0, "engine_max_rpm": 7800.0})
        self.assertEqual(d["rpm_ratio"], 1.0)

    def test_regime_max_nul_ne_divise_pas_par_zero(self):
        """En menu, le jeu envoie des zeros partout."""
        d = compute({"current_engine_rpm": 0.0, "engine_max_rpm": 0.0})
        self.assertEqual(d["rpm_ratio"], 0.0)


class TestGlissement(unittest.TestCase):
    def test_maximum_des_quatre_roues(self):
        d = compute({"tire_combined_slip_fl": 0.2, "tire_combined_slip_fr": 1.4,
                     "tire_combined_slip_rl": 0.1, "tire_combined_slip_rr": 0.9})
        self.assertAlmostEqual(d["slip_max"], 1.4, places=6)

    def test_valeur_absolue(self):
        """Un glissement negatif est une perte d'adherence tout autant."""
        d = compute({"tire_combined_slip_fl": -2.5, "tire_combined_slip_fr": 0.1,
                     "tire_combined_slip_rl": 0.0, "tire_combined_slip_rr": 0.0})
        self.assertAlmostEqual(d["slip_max"], 2.5, places=6)


class TestDonneesIncompletes(unittest.TestCase):
    def test_trame_vide(self):
        self.assertEqual(compute({}), {})

    def test_champs_partiels(self):
        d = compute({"speed": 5.0})
        self.assertIn("speed_kmh", d)
        self.assertNotIn("rpm_ratio", d)
        self.assertNotIn("throttle", d)

    def test_valeurs_non_numeriques_ignorees(self):
        d = compute({"speed": None, "accel": "x", "steer": 0})
        self.assertNotIn("speed_kmh", d)
        self.assertNotIn("throttle", d)
        self.assertIn("steer_norm", d)


class TestCoherence(unittest.TestCase):
    def test_tous_les_derives_produits_sur_une_trame_complete(self):
        trame = {
            "speed": 30.0, "accel": 200, "brake": 10, "clutch": 0, "hand_brake": 0,
            "steer": 40, "acceleration_x": 1.0, "acceleration_y": 2.0,
            "acceleration_z": 3.0, "yaw": 0.5, "pitch": 0.1, "roll": -0.2,
            "tire_temp_fl": 180.0, "tire_temp_fr": 181.0,
            "tire_temp_rl": 182.0, "tire_temp_rr": 183.0,
            "current_engine_rpm": 5000.0, "engine_max_rpm": 8000.0,
            "tire_combined_slip_fl": 0.1, "tire_combined_slip_fr": 0.2,
            "tire_combined_slip_rl": 0.3, "tire_combined_slip_rr": 0.4,
        }
        produits = compute(trame)
        self.assertEqual(sorted(produits), sorted(DERIVED_CHANNELS))

    def test_chaque_derive_declare_une_unite(self):
        sans = [n for n in DERIVED_CHANNELS if n not in DERIVED_UNITS]
        self.assertEqual(sans, [])

    def test_unites_publiees_dans_le_catalogue(self):
        for nom in DERIVED_CHANNELS:
            with self.subTest(canal=nom):
                self.assertIn(nom, UNITS)


if __name__ == "__main__":
    unittest.main()
