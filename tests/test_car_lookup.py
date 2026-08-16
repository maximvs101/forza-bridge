"""Correspondance ordinal -> vehicule et libelles d'enumerations."""

import unittest

import car_lookup


class TestCarName(unittest.TestCase):
    def test_ordinal_connu(self):
        self.assertEqual(car_lookup.car_name(292), "2003 Porsche Carrera GT")
        self.assertEqual(car_lookup.car_name(249), "1964 Ferrari 250 GTO")

    def test_ordinal_verifie_en_jeu(self):
        """Releve sur FH6 le 28 juillet 2026 et confirme par l'utilisateur."""
        self.assertEqual(car_lookup.car_name(3917), "2023 Audi R8 GT")

    def test_ordinal_flottant(self):
        """La telemetrie fournit parfois les entiers sous forme de float."""
        self.assertEqual(car_lookup.car_name(292.0), "2003 Porsche Carrera GT")

    def test_ordinal_inconnu(self):
        self.assertIsNone(car_lookup.car_name(999999))
        self.assertIn("999999", car_lookup.describe(999999))

    def test_absence_de_vehicule(self):
        for valeur in (None, 0):
            with self.subTest(valeur=valeur):
                self.assertEqual(car_lookup.describe(valeur), "-")

    def test_table_non_vide(self):
        self.assertGreater(car_lookup.known_count(), 600)


class TestLibelles(unittest.TestCase):
    def test_drivetrain(self):
        self.assertEqual(car_lookup.drivetrain_label(0), "FWD")
        self.assertEqual(car_lookup.drivetrain_label(1), "RWD")
        self.assertEqual(car_lookup.drivetrain_label(2), "AWD")

    def test_drivetrain_hors_plage(self):
        for valeur in (9, -1, None, "x"):
            with self.subTest(valeur=valeur):
                self.assertEqual(car_lookup.drivetrain_label(valeur), "-")

    def test_classe_s1_verifiee_en_jeu(self):
        """FH6 affiche "S1 769" pour l'Audi R8 GT, qui remonte car_class=4.

        Ne pas "corriger" cette table en croisant avec le PI : les bandes
        classiques FH4/FH5 (S1 = 801-900) ne s'appliquent pas a FH6.
        """
        self.assertEqual(car_lookup.car_class_label(4), "S1")

    def test_classes(self):
        self.assertEqual(car_lookup.car_class_label(0), "D")
        self.assertEqual(car_lookup.car_class_label(3), "A")
        self.assertEqual(car_lookup.car_class_label(None), "-")


if __name__ == "__main__":
    unittest.main()
