"""Lissage temporel par canal.

Le lissage est ADDITIF : il publie `<canal>_smooth` et ne touche jamais au
canal d'origine. Un filtre deforme par construction — il retarde et rabote
les extremes — donc ecraser la valeur brute falsifierait la telemetrie pour
tous les consommateurs, dont ceux qui l'analysent ou l'enregistrent.
"""

import math
import unittest

from smoothing import (NOT_SMOOTHABLE, SUFFIX, Smoother, format_settings,
                       parse_settings)


class TestLectureDesReglages(unittest.TestCase):
    def test_specification_simple(self):
        self.assertEqual(parse_settings("speed_kmh=0.15"), {"speed_kmh": 0.15})

    def test_plusieurs_canaux(self):
        lu = parse_settings("speed_kmh=0.15, slip_max=0.05 ; throttle=0.2")
        self.assertEqual(lu, {"speed_kmh": 0.15, "slip_max": 0.05, "throttle": 0.2})

    def test_entrees_invalides_ignorees(self):
        """Le texte vient d'un champ de saisie : rien ne doit lever."""
        for texte in ("", "n'importe quoi", "speed_kmh", "speed_kmh=abc",
                      "=0.2", "speed_kmh=-1", "speed_kmh=0"):
            with self.subTest(texte=texte):
                self.assertEqual(parse_settings(texte), {})

    def test_canal_non_lissable_refuse(self):
        self.assertEqual(parse_settings("gear=0.2"), {})
        self.assertEqual(parse_settings("car_ordinal=0.5"), {})

    def test_aller_retour(self):
        reglages = {"speed_kmh": 0.15, "throttle": 0.05}
        self.assertEqual(parse_settings(format_settings(reglages)), reglages)


class TestNonAlteration(unittest.TestCase):
    """La garantie centrale : les donnees du jeu ne sont pas modifiees."""

    def test_canal_d_origine_jamais_modifie(self):
        s = Smoother({"speed_kmh": 0.5})
        instant = 0.0
        s.apply({"speed_kmh": 0.0}, instant)
        for valeur in (10.0, 200.0, 250.0, 30.0):
            instant += 0.1
            sortie = s.apply({"speed_kmh": valeur}, instant)
            self.assertEqual(sortie["speed_kmh"], valeur)

    def test_le_lisse_est_un_canal_distinct(self):
        s = Smoother({"speed_kmh": 0.5})
        s.apply({"speed_kmh": 0.0}, 0.0)
        sortie = s.apply({"speed_kmh": 200.0}, 0.1)
        self.assertIn("speed_kmh" + SUFFIX, sortie)
        self.assertNotEqual(sortie["speed_kmh" + SUFFIX], sortie["speed_kmh"])

    def test_pics_conserves_dans_le_brut(self):
        """Le lisse rabote les extremes ; le brut doit les garder intacts."""
        s = Smoother({"speed_kmh": 0.5})
        instant, bruts, lisses = 0.0, [], []
        for i in range(120):
            instant += 1 / 60
            valeur = 100.0 + (100.0 if i % 30 < 15 else -100.0)
            sortie = s.apply({"speed_kmh": valeur}, instant)
            bruts.append(sortie["speed_kmh"])
            lisses.append(sortie["speed_kmh" + SUFFIX])
        self.assertEqual(max(bruts), 200.0)
        self.assertEqual(min(bruts), 0.0)
        self.assertLess(max(lisses[30:]), 200.0, "le lisse doit etre rabote")
        self.assertGreater(min(lisses[30:]), 0.0)

    def test_produced_channels_annonces(self):
        s = Smoother({"speed_kmh": 0.2, "slip_max": 0.1})
        self.assertEqual(s.produced_channels, ["slip_max_smooth", "speed_kmh_smooth"])

    def test_aucun_canal_produit_sans_reglage(self):
        self.assertEqual(Smoother().produced_channels, [])


class TestFiltre(unittest.TestCase):
    def test_inactif_par_defaut(self):
        s = Smoother()
        self.assertFalse(s.active)
        trame = {"speed_kmh": 100.0}
        self.assertIs(s.apply(trame, 1.0), trame)

    def test_premiere_valeur_adoptee_telle_quelle(self):
        """Partir de zero produirait une rampe visible au demarrage."""
        s = Smoother({"speed_kmh": 0.2})
        sortie = s.apply({"speed_kmh": 100.0}, 0.0)
        self.assertEqual(sortie["speed_kmh" + SUFFIX], 100.0)

    def test_convergence_vers_la_valeur_cible(self):
        s = Smoother({"speed_kmh": 0.1})
        s.apply({"speed_kmh": 0.0}, 0.0)
        instant = 0.0
        for _ in range(200):
            instant += 1 / 60
            sortie = s.apply({"speed_kmh": 100.0}, instant)
        self.assertAlmostEqual(sortie["speed_kmh" + SUFFIX], 100.0, places=3)

    def test_retard_reel_avant_convergence(self):
        """Contre-epreuve du test precedent : si le filtre ne faisait rien,
        la sortie serait deja a la cible des la premiere trame."""
        s = Smoother({"speed_kmh": 1.0})
        s.apply({"speed_kmh": 0.0}, 0.0)
        sortie = s.apply({"speed_kmh": 100.0}, 0.05)
        self.assertLess(sortie["speed_kmh" + SUFFIX], 20.0)

    def test_constante_de_temps_respectee(self):
        """Apres un echelon, 63 % de l'ecart doit etre franchi au bout de tau."""
        tau = 0.5
        s = Smoother({"speed_kmh": tau})
        s.apply({"speed_kmh": 0.0}, 0.0)
        instant = 0.0
        while instant < tau - 1e-9:
            instant = min(instant + 1 / 240, tau)
            sortie = s.apply({"speed_kmh": 100.0}, instant)
        attendu = 100.0 * (1 - math.exp(-1))
        self.assertAlmostEqual(sortie["speed_kmh" + SUFFIX], attendu, delta=1.0)

    def test_independant_de_la_cadence(self):
        """Point cle : la source passe de 60 Hz a l'arret a 30 Hz en roulant.

        Un coefficient fixe lisserait deux fois plus fort en menu ; en partant
        de l'ecart de temps, les trois cadences doivent converger pareil.
        """
        resultats = []
        for cadence in (30, 60, 120):
            s = Smoother({"speed_kmh": 0.2})
            s.apply({"speed_kmh": 0.0}, 0.0)
            instant = 0.0
            for _ in range(cadence):  # exactement une seconde
                instant += 1 / cadence
                sortie = s.apply({"speed_kmh": 100.0}, instant)
            resultats.append(sortie["speed_kmh" + SUFFIX])
        for valeur in resultats[1:]:
            self.assertAlmostEqual(valeur, resultats[0], delta=0.5)

    def test_bruit_fortement_reduit(self):
        """Signal alternant de +/- 0,5 autour de 1,0 : le lisse doit se
        resserrer, alors que le brut garde toute son amplitude."""
        s = Smoother({"slip_max": 0.3})
        instant = 0.0
        s.apply({"slip_max": 1.0}, instant)
        bruts, lisses = [], []
        for i in range(180):
            instant += 1 / 60
            brut = 1.0 + (0.5 if i % 2 else -0.5)
            sortie = s.apply({"slip_max": brut}, instant)
            bruts.append(sortie["slip_max"])
            lisses.append(sortie["slip_max" + SUFFIX])
        etendue_brute = max(bruts[60:]) - min(bruts[60:])
        etendue_lissee = max(lisses[60:]) - min(lisses[60:])
        self.assertAlmostEqual(etendue_brute, 1.0, places=6)
        self.assertLess(etendue_lissee, 0.1, "le bruit devrait etre fortement reduit")


class TestGardeFous(unittest.TestCase):
    def test_canaux_non_lissables_intouches(self):
        s = Smoother({"speed_kmh": 0.2})
        s.configure({"speed_kmh": 0.2, "gear": 0.2})
        self.assertNotIn("gear", s.settings)

    def test_gear_ne_produit_aucun_lisse(self):
        """Une moyenne entre deux rapports donnerait 2,7."""
        s = Smoother(parse_settings("gear=0.5, speed_kmh=0.2"))
        s.apply({"gear": 2, "speed_kmh": 50.0}, 0.0)
        sortie = s.apply({"gear": 3, "speed_kmh": 100.0}, 0.1)
        self.assertEqual(sortie["gear"], 3)
        self.assertNotIn("gear" + SUFFIX, sortie)

    def test_valeurs_non_numeriques_traversent(self):
        s = Smoother({"car_name": 0.2, "speed_kmh": 0.2})
        sortie = s.apply({"car_name": "Audi R8", "speed_kmh": 10.0}, 0.0)
        self.assertEqual(sortie["car_name"], "Audi R8")
        self.assertNotIn("car_name" + SUFFIX, sortie)

    def test_non_fini_ne_contamine_pas_l_etat(self):
        """Sans garde, l'etat deviendrait NaN et le canal ne s'en remettrait
        jamais."""
        s = Smoother({"speed_kmh": 0.2})
        s.apply({"speed_kmh": 50.0}, 0.0)

        sortie = s.apply({"speed_kmh": float("nan")}, 0.1)
        self.assertTrue(math.isnan(sortie["speed_kmh"]), "le brut passe tel quel")
        self.assertNotIn("speed_kmh" + SUFFIX, sortie)

        suite = s.apply({"speed_kmh": 50.0}, 0.2)
        self.assertTrue(math.isfinite(suite["speed_kmh" + SUFFIX]))
        self.assertAlmostEqual(suite["speed_kmh" + SUFFIX], 50.0, places=6)

    def test_champ_absent_ignore(self):
        s = Smoother({"speed_kmh": 0.2})
        self.assertEqual(s.apply({"autre": 1.0}, 0.0), {"autre": 1.0})

    def test_ecart_de_temps_nul_ou_negatif(self):
        s = Smoother({"speed_kmh": 0.2})
        s.apply({"speed_kmh": 10.0}, 5.0)
        sortie = s.apply({"speed_kmh": 20.0}, 5.0)
        self.assertEqual(sortie["speed_kmh" + SUFFIX], 20.0)


class TestReset(unittest.TestCase):
    def test_reset_repart_de_la_nouvelle_valeur(self):
        """Au changement de vehicule, la sortie ne doit pas glisser depuis
        l'ancienne valeur."""
        s = Smoother({"speed_kmh": 1.0})
        s.apply({"speed_kmh": 200.0}, 0.0)
        s.apply({"speed_kmh": 200.0}, 0.1)
        s.reset()
        self.assertEqual(s.apply({"speed_kmh": 0.0}, 0.2)["speed_kmh" + SUFFIX], 0.0)

    def test_configure_oublie_les_canaux_retires(self):
        s = Smoother({"speed_kmh": 0.2, "throttle": 0.2})
        s.apply({"speed_kmh": 100.0, "throttle": 1.0}, 0.0)
        s.configure({"speed_kmh": 0.2})
        self.assertEqual(s.settings, {"speed_kmh": 0.2})


class TestListeNonLissables(unittest.TestCase):
    def test_contient_les_entiers_significatifs(self):
        for nom in ("gear", "lap_number", "car_ordinal", "is_race_on"):
            with self.subTest(canal=nom):
                self.assertIn(nom, NOT_SMOOTHABLE)


if __name__ == "__main__":
    unittest.main()
