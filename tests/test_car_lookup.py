"""Correspondance ordinal -> vehicule et libelles d'enumerations."""

import pathlib
import unittest

import car_lookup


class BaseJournalIsole(unittest.TestCase):
    """Redirige le journal des inconnus vers un fichier jetable.

    `describe()` a un effet de bord : sans cette isolation, la suite de tests
    inscrivait un ordinal fictif dans le vrai car_ordinals_unknown.json, que
    l'outil de mise a jour rapportait ensuite comme une observation reelle
    en jeu.
    """

    def setUp(self):
        self._sauvegarde = set(car_lookup._inconnus)
        self._charges = car_lookup._inconnus_charges
        car_lookup._inconnus.clear()
        car_lookup._inconnus_charges = True  # evite de relire le vrai fichier
        self._fichier = car_lookup.UNKNOWN_PATH
        jetable = pathlib.Path(__file__).with_name("_inconnus_test.json")
        car_lookup.UNKNOWN_PATH = jetable
        car_lookup._UNKNOWN_PATH = jetable

    def tearDown(self):
        if car_lookup._UNKNOWN_PATH.exists():
            car_lookup._UNKNOWN_PATH.unlink()
        car_lookup.UNKNOWN_PATH = self._fichier
        car_lookup._UNKNOWN_PATH = self._fichier
        car_lookup._inconnus.clear()
        car_lookup._inconnus.update(self._sauvegarde)
        car_lookup._inconnus_charges = self._charges


class TestCarName(BaseJournalIsole):
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


class TestOrdinauxInconnus(BaseJournalIsole):
    """La table vient d'une liste communautaire figee : les voitures ajoutees
    par les mises a jour du jeu y manquent forcement. Les retenir evite de
    decouvrir le manque par hasard."""

    def test_ordinal_inconnu_retenu(self):
        car_lookup.describe(987001)
        self.assertIn(987001, car_lookup.unknown_seen())

    def test_ordinal_connu_non_retenu(self):
        car_lookup.describe(3917)
        self.assertEqual(car_lookup.unknown_seen(), [])

    def test_absence_de_vehicule_non_retenue(self):
        """En menu le jeu envoie l'ordinal 0 : ce n'est pas une voiture
        manquante, et l'inscrire polluerait le journal."""
        car_lookup.describe(0)
        car_lookup.describe(None)
        self.assertEqual(car_lookup.unknown_seen(), [])

    def test_ecrit_sur_disque(self):
        car_lookup.describe(987002)
        import json
        contenu = json.loads(car_lookup._UNKNOWN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contenu, [987002])

    def test_pas_de_doublon(self):
        for _ in range(5):
            car_lookup.describe(987003)
        self.assertEqual(car_lookup.unknown_seen(), [987003])

    def test_journal_existant_repris(self):
        """Le fichier etait en ecriture seule : le premier inconnu d'une
        nouvelle session ecrasait tout l'historique."""
        import json
        car_lookup._UNKNOWN_PATH.write_text(json.dumps([111111, 222222]),
                                            encoding="utf-8")
        car_lookup._inconnus.clear()
        car_lookup._inconnus_charges = False

        car_lookup.describe(333333)
        self.assertEqual(json.loads(car_lookup._UNKNOWN_PATH.read_text(encoding="utf-8")),
                         [111111, 222222, 333333])

    def test_ecriture_atomique(self):
        """Aucun fichier temporaire ne doit subsister."""
        car_lookup.describe(444444)
        residus = list(car_lookup._UNKNOWN_PATH.parent.glob("*.tmp"))
        self.assertEqual(residus, [])


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
