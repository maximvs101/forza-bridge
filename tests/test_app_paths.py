"""Ou le programme ecrit, selon qu'il tourne depuis les sources ou gele.

PyInstaller extrait l'executable dans un dossier TEMPORAIRE efface a la
sortie. Y ecrire `config.json` revient a perdre les reglages a chaque
fermeture, sans message : la case cochee hier ne l'est plus aujourd'hui, et
rien n'explique pourquoi. Le journal des ordinaux inconnus subirait le meme
sort, ce qui viderait de son sens l'outil d'entretien.

Ces tests portent sur la SEPARATION : ce qui est livre avec le programme se
lit la ou il est ; ce qui doit survivre s'ecrit chez l'utilisateur.
"""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

import app_paths


class GeleTestCase(unittest.TestCase):
    """Simule l'executable : `sys.frozen` et un APPDATA jetable."""

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self._appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._dossier.name
        self._frozen = getattr(sys, "frozen", None)
        sys.frozen = True
        importlib.reload(app_paths)

    def tearDown(self):
        if self._frozen is None:
            del sys.frozen
        else:
            sys.frozen = self._frozen
        if self._appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._appdata
        importlib.reload(app_paths)
        self._dossier.cleanup()


class TestDepuisLesSources(unittest.TestCase):
    def test_etat_a_cote_du_code(self):
        """Comportement d'origine preserve : deplacer la configuration des
        utilisateurs du depot serait une regression silencieuse."""
        self.assertFalse(app_paths.FROZEN)
        self.assertEqual(app_paths.state_path("config.json").parent,
                         app_paths.SOURCE_DIR)

    def test_donnees_a_cote_du_code(self):
        self.assertEqual(app_paths.data_path("car_ordinals.json"),
                         app_paths.SOURCE_DIR / "car_ordinals.json")

    def test_la_table_livree_est_lisible(self):
        import car_lookup
        self.assertTrue(car_lookup.DATA_PATH.is_file())
        self.assertGreater(car_lookup.known_count(), 100)

    def test_overlay_servi_depuis_le_dossier_livre(self):
        import http_assets
        self.assertTrue((http_assets.WEB_ROOT / "overlay.html").is_file())


class TestGele(GeleTestCase):
    def test_etat_hors_du_dossier_du_programme(self):
        """LE point : sous PyInstaller, SOURCE_DIR est temporaire."""
        cible = app_paths.state_path("config.json")
        self.assertNotEqual(cible.parent, app_paths.SOURCE_DIR)
        self.assertEqual(cible.parent.name, app_paths.APP_NAME)
        self.assertTrue(cible.parent.is_dir())

    def test_le_dossier_est_reellement_inscriptible(self):
        cible = app_paths.state_path("essai.json")
        cible.write_text("{}", encoding="utf-8")
        self.assertEqual(cible.read_text(encoding="utf-8"), "{}")

    def test_donnees_livrees_suivent_le_programme(self):
        """Contre-epreuve : la table des vehicules et l'overlay sont livres
        AVEC l'executable, donc ils restent a cote des modules — dossier
        temporaire compris. Les deplacer les rendrait introuvables."""
        self.assertEqual(app_paths.data_path("car_ordinals.json").parent,
                         app_paths.SOURCE_DIR)

    def test_repli_si_le_dossier_utilisateur_est_inaccessible(self):
        os.environ["APPDATA"] = str(Path(self._dossier.name) / "fichier")
        Path(os.environ["APPDATA"]).write_text("pas un dossier", encoding="utf-8")
        importlib.reload(app_paths)
        # Un chemin est renvoye malgre tout : echouer ici empecherait le
        # programme de demarrer.
        self.assertIsInstance(app_paths.state_path("config.json"), Path)


class TestModulesCables(unittest.TestCase):
    """Les modules doivent utiliser ces chemins, sinon la separation ne sert
    a rien."""

    def test_configuration_par_state_path(self):
        import gui
        self.assertEqual(gui.CONFIG_PATH, app_paths.state_path("config.json"))

    def test_journal_des_inconnus_par_state_path(self):
        import car_lookup
        self.assertEqual(car_lookup.UNKNOWN_PATH,
                         app_paths.state_path("car_ordinals_unknown.json"))

    def test_table_des_vehicules_par_data_path(self):
        import car_lookup
        self.assertEqual(car_lookup.DATA_PATH,
                         app_paths.data_path("car_ordinals.json"))

    def test_outil_et_programme_ecrivent_au_meme_endroit(self):
        """Deja verifie ailleurs, repete ici : la separation ne doit pas
        avoir fait diverger l'outil d'entretien du module qu'il alimente."""
        import car_lookup
        sys.path.insert(0, str(app_paths.SOURCE_DIR / "tools"))
        import update_car_table as outil
        self.assertEqual(outil.TABLE, car_lookup.DATA_PATH)
        self.assertEqual(outil.INCONNUS, car_lookup.UNKNOWN_PATH)


if __name__ == "__main__":
    unittest.main()
