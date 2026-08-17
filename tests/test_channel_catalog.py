"""Coherence du catalogue de canaux.

Ces tests visent une classe de defaut qui s'est deja produite deux fois :
une liste de canaux qui derive de ce que le code emet reellement.
"""

import ast
import unittest
from pathlib import Path

from channel_catalog import (ALL_CHANNELS, CATEGORIES, CATEGORY_OF,
                             DEFAULT_SELECTION, RAW_CHANNELS, UNITS)
from derived_channels import DERIVED_CHANNELS
from forza_telemetry import _HORIZON_DASH_WEAR

# Reference = la variante de paquet la PLUS LARGE (dash + usure des pneus).
# Prendre la variante courte laisserait les quatre canaux d'usure passer pour
# des canaux fantomes alors qu'ils sont bel et bien decodes, a 339 octets.
CHAMPS_DECODES = [name for name, _ in _HORIZON_DASH_WEAR]

BUILDER_TD = (Path(__file__).resolve().parents[1]
              / "touchdesigner" / "build_forza_bridge_component.py")


def categories_du_builder_td() -> dict:
    """Extrait la constante CATEGORIES du script constructeur TouchDesigner.

    Le fichier est lu avec `ast` plutot qu'importe : il appelle build() a
    l'import, ce qui n'a de sens que dans TouchDesigner.
    """
    arbre = ast.parse(BUILDER_TD.read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign):
            for cible in noeud.targets:
                if isinstance(cible, ast.Name) and cible.id == "CATEGORIES":
                    return ast.literal_eval(noeud.value)
    raise AssertionError("CATEGORIES introuvable dans le script TouchDesigner")


class TestCatalogueContreDecodage(unittest.TestCase):
    def test_aucun_champ_emis_hors_catalogue(self):
        """Un champ decode mais absent du catalogue serait diffuse sans
        apparaitre dans aucune liste (interface, table TD, accueil WebSocket).
        """
        manquants = [n for n in CHAMPS_DECODES if n not in set(ALL_CHANNELS)]
        self.assertEqual(manquants, [], f"champs emis mais non catalogues: {manquants}")

    def test_canaux_bruts_exactement_les_champs_decodes(self):
        self.assertEqual(sorted(RAW_CHANNELS), sorted(CHAMPS_DECODES))

    def test_aucun_canal_fantome(self):
        """Tout canal catalogue doit etre soit decode du paquet, soit calcule."""
        connus = set(CHAMPS_DECODES) | set(DERIVED_CHANNELS)
        orphelins = [n for n in ALL_CHANNELS if n not in connus]
        self.assertEqual(orphelins, [], f"canaux catalogues mais jamais emis: {orphelins}")

    def test_derives_ne_masquent_aucun_canal_brut(self):
        """Un derive portant le nom d'un champ brut ecraserait la valeur du
        jeu au moment de la fusion dans le pont."""
        collisions = sorted(set(DERIVED_CHANNELS) & set(CHAMPS_DECODES))
        self.assertEqual(collisions, [], f"noms en collision: {collisions}")

    def test_pas_de_doublon(self):
        self.assertEqual(len(ALL_CHANNELS), len(set(ALL_CHANNELS)))


class TestUnites(unittest.TestCase):
    def test_chaque_canal_a_une_unite(self):
        """Publiees dans l'accueil WebSocket : sans elles, un consommateur ne
        distingue pas "sans dimension" de "unite oubliee"."""
        sans = [n for n in ALL_CHANNELS if n not in UNITS]
        self.assertEqual(sans, [], f"canaux sans unite: {sans}")

    def test_pas_d_unite_orpheline(self):
        orphelines = [n for n in UNITS if n not in set(ALL_CHANNELS)]
        self.assertEqual(orphelines, [])


class TestSelectionParDefaut(unittest.TestCase):
    def test_incluse_dans_le_catalogue(self):
        self.assertTrue(DEFAULT_SELECTION.issubset(set(ALL_CHANNELS)))

    def test_contient_engine_max_rpm(self):
        """Reference de mise a l'echelle de toute jauge de regime : sans lui,
        les consommateurs retombent sur une valeur devinee."""
        self.assertIn("engine_max_rpm", DEFAULT_SELECTION)

    def test_champs_non_documentes_decoches(self):
        self.assertNotIn("horizon_unknown_1", DEFAULT_SELECTION)
        self.assertNotIn("horizon_unknown_2", DEFAULT_SELECTION)


class TestCategorieDeChaqueCanal(unittest.TestCase):
    def test_categorie_pour_tous(self):
        for name in ALL_CHANNELS:
            with self.subTest(canal=name):
                self.assertIn(name, CATEGORY_OF)


class TestSynchroAvecTouchDesigner(unittest.TestCase):
    def test_catalogue_td_identique(self):
        """Le script constructeur TouchDesigner duplique le catalogue pour
        rester autonome dans un Text DAT. Cette duplication a deja diverge
        une fois : ce test la rattrape.
        """
        self.assertEqual(categories_du_builder_td(), CATEGORIES)


if __name__ == "__main__":
    unittest.main()
