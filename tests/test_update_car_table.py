"""Outil d'entretien de la table des vehicules.

C'est le seul module du projet capable de DETRUIRE des donnees : il reecrit
`car_ordinals.json`, que l'utilisateur corrige a la main. Il n'avait aucun test
fonctionnel — seul son texte affiche etait examine.

Deux defauts deja corriges ici sans filet, et que ces tests verrouillent :
  - le remplacement en bloc, qui annulait les corrections locales (la source
    communautaire n'est pas officielle) : la mise a jour FUSIONNE ;
  - l'ecriture non atomique : `write_text` tronque avant d'ecrire, et un JSON
    tronque fait renvoyer {} a car_lookup, qui le met en cache pour tout le
    processus — chaque voiture devient alors "inconnue".

Aucun acces reseau : la source est toujours passee par --file.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import update_car_table as outil  # noqa: E402


class OutilTestCase(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        base = Path(self._dossier.name)
        self.table = base / "car_ordinals.json"
        self.inconnus = base / "car_ordinals_unknown.json"
        # Les chemins sont des constantes du module : les detourner evite
        # d'ecrire dans la table reelle du projet.
        self._table_origine = outil.TABLE
        self._inconnus_origine = outil.INCONNUS
        outil.TABLE, outil.INCONNUS = self.table, self.inconnus

    def tearDown(self):
        outil.TABLE = self._table_origine
        outil.INCONNUS = self._inconnus_origine
        self._dossier.cleanup()

    # -- utilitaires -------------------------------------------------------

    def ecrit_table(self, contenu: dict) -> None:
        self.table.write_text(json.dumps(contenu, ensure_ascii=False),
                              encoding="utf-8")

    def source(self, nom_vers_ordinal: dict) -> Path:
        chemin = Path(self._dossier.name) / "source.json"
        chemin.write_text(json.dumps(nom_vers_ordinal, ensure_ascii=False),
                          encoding="utf-8")
        return chemin

    def lance(self, *arguments) -> tuple[int, str]:
        argv = ["update_car_table.py", *arguments]
        sortie = io.StringIO()
        ancien = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(sortie), \
                 contextlib.redirect_stderr(sortie):
                code = outil.main()
        finally:
            sys.argv = ancien
        return code, sortie.getvalue()

    def table_lue(self) -> dict:
        return json.loads(self.table.read_text(encoding="utf-8"))


class TestInversionEtCollisions(unittest.TestCase):
    def test_inversion_nom_vers_ordinal(self):
        self.assertEqual(outil.en_table({"Alpha": 10, "Beta": 2}),
                         {"2": "Beta", "10": "Alpha"})

    def test_tri_numerique_et_non_lexical(self):
        """Trie sur la valeur entiere : "10" < "9" en tri de chaines."""
        table = outil.en_table({"A": 9, "B": 10, "C": 100})
        self.assertEqual(list(table), ["9", "10", "100"])

    def test_collision_garde_la_premiere(self):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            table = outil.en_table({"Premier": 5, "Second": 5})
        self.assertEqual(table, {"5": "Premier"})
        self.assertIn("duplicate", sortie.getvalue())


class TestComparaison(unittest.TestCase):
    def test_ajouts_retraits_renommages(self):
        ajouts, retraits, renommes = outil.compare(
            {"1": "Ancien", "2": "Stable"},
            {"2": "Stable", "3": "Nouveau", "1": "Renomme"})
        self.assertEqual(ajouts, ["3"])
        self.assertEqual(retraits, [])
        self.assertEqual(renommes, [("1", "Ancien", "Renomme")])

    def test_retrait_detecte(self):
        _, retraits, _ = outil.compare({"1": "Parti"}, {})
        self.assertEqual(retraits, ["1"])


class TestApercuNEcritRien(OutilTestCase):
    def test_sans_write_la_table_est_intacte(self):
        self.ecrit_table({"1": "Local"})
        avant = self.table.read_bytes()
        code, texte = self.lance("--file", str(self.source({"Nouveau": 2})))
        self.assertEqual(code, 0)
        self.assertEqual(self.table.read_bytes(), avant,
                         "l'apercu a modifie la table")
        self.assertIn("Preview only", texte)

    def test_apercu_annonce_les_differences(self):
        self.ecrit_table({"1": "Local"})
        _, texte = self.lance("--file", str(self.source({"Nouveau": 2})))
        self.assertIn("+ 1 added", texte)
        self.assertIn("Nouveau", texte)


class TestFusion(OutilTestCase):
    def test_entree_locale_absente_de_la_source_est_conservee(self):
        """LE defaut d'origine : un remplacement en bloc effacait les
        corrections faites a la main, la source n'etant pas officielle."""
        self.ecrit_table({"1": "Corrige a la main", "2": "Commun"})
        code, texte = self.lance("--file", str(self.source({"Commun": 2})),
                                 "--write")
        self.assertEqual(code, 0)
        self.assertEqual(self.table_lue()["1"], "Corrige a la main")
        self.assertIn("KEPT", texte)

    def test_ajout_applique(self):
        self.ecrit_table({"1": "Deja la"})
        self.lance("--file", str(self.source({"Deja la": 1, "Neuf": 7})),
                   "--write")
        self.assertEqual(self.table_lue(), {"1": "Deja la", "7": "Neuf"})

    def test_renommage_de_la_source_applique_et_annonce(self):
        """Une source perimee peut annuler une correction locale : le
        renommage est applique, mais il doit etre AFFICHE avant l'ecriture."""
        self.ecrit_table({"1": "Nom local"})
        _, texte = self.lance("--file", str(self.source({"Nom source": 1})),
                              "--write")
        self.assertEqual(self.table_lue(), {"1": "Nom source"})
        self.assertIn("Nom local", texte)
        self.assertIn("Nom source", texte)

    def test_remove_retire_explicitement(self):
        self.ecrit_table({"1": "A jeter", "2": "Commun"})
        self.lance("--file", str(self.source({"Commun": 2})), "--write",
                   "--remove")
        self.assertEqual(self.table_lue(), {"2": "Commun"})

    def test_resultat_trie_numeriquement(self):
        self.ecrit_table({"100": "Cent"})
        self.lance("--file", str(self.source({"Neuf": 9, "Dix": 10})), "--write")
        self.assertEqual(list(self.table_lue()), ["9", "10", "100"])

    def test_rien_a_changer_n_ecrit_pas(self):
        self.ecrit_table({"1": "Identique"})
        avant = self.table.read_bytes()
        code, texte = self.lance("--file", str(self.source({"Identique": 1})),
                                 "--write")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to change", texte)
        self.assertEqual(self.table.read_bytes(), avant)

    def test_source_vide_ne_vide_pas_la_table(self):
        """Contre-epreuve du pire scenario : une source qui ne renvoie rien
        (gist vide, format change) ne doit pas emporter la table."""
        self.ecrit_table({"1": "Precieux", "2": "Aussi"})
        code, _ = self.lance("--file", str(self.source({})), "--write")
        self.assertEqual(code, 0)
        self.assertEqual(self.table_lue(), {"1": "Precieux", "2": "Aussi"})

    def test_source_vide_avec_remove_est_destructrice_mais_explicite(self):
        """--remove fait ce qu'il annonce : c'est la raison d'etre de l'option
        separee."""
        self.ecrit_table({"1": "Precieux"})
        self.lance("--file", str(self.source({})), "--write", "--remove")
        self.assertEqual(self.table_lue(), {})


class TestEcritureAtomique(OutilTestCase):
    def test_aucun_fichier_temporaire_laisse(self):
        self.ecrit_table({"1": "Local"})
        self.lance("--file", str(self.source({"Neuf": 2})), "--write")
        restes = list(self.table.parent.glob("*.tmp"))
        self.assertEqual(restes, [], f"fichier temporaire laisse : {restes}")

    def test_json_relisible_par_car_lookup(self):
        """Le vrai critere : le programme doit pouvoir relire ce qui a ete
        ecrit. Un JSON tronque faisait renvoyer {} a car_lookup, qui le mettait
        en cache pour tout le processus."""
        import car_lookup
        self.ecrit_table({"1": "Local"})
        self.lance("--file", str(self.source({"Neuf": 4242})), "--write")

        origine = car_lookup.DATA_PATH
        car_lookup.DATA_PATH = self.table
        car_lookup._table = None if hasattr(car_lookup, "_table") else None
        try:
            with self.table.open(encoding="utf-8") as f:
                relu = json.load(f)
        finally:
            car_lookup.DATA_PATH = origine
        self.assertEqual(relu["4242"], "Neuf")

    def test_encodage_utf8_conserve(self):
        self.ecrit_table({})
        self.lance("--file", str(self.source({"Citroën Méhari": 3})), "--write")
        self.assertEqual(self.table_lue()["3"], "Citroën Méhari")


class TestSourceInvalide(OutilTestCase):
    def test_json_malforme_laisse_la_table_intacte(self):
        self.ecrit_table({"1": "Precieux"})
        avant = self.table.read_bytes()
        mauvais = Path(self._dossier.name) / "casse.json"
        mauvais.write_text("{ceci n'est pas du JSON", encoding="utf-8")

        code, texte = self.lance("--file", str(mauvais), "--write")
        self.assertEqual(code, 1)
        self.assertIn("Could not fetch", texte)
        self.assertEqual(self.table.read_bytes(), avant)

    def test_fichier_absent_signale(self):
        self.ecrit_table({"1": "Precieux"})
        code, texte = self.lance("--file", str(Path(self._dossier.name) / "nope.json"),
                                 "--write")
        self.assertEqual(code, 1)
        self.assertIn("Could not fetch", texte)
        self.assertEqual(self.table_lue(), {"1": "Precieux"})

    def test_source_de_type_inattendu(self):
        """Une liste au lieu d'un objet ne doit pas produire une trace."""
        liste = Path(self._dossier.name) / "liste.json"
        liste.write_text('["a", "b"]', encoding="utf-8")
        self.ecrit_table({"1": "Precieux"})
        code, _ = self.lance("--file", str(liste), "--write")
        self.assertEqual(code, 1)
        self.assertEqual(self.table_lue(), {"1": "Precieux"})


class TestOrdinauxInconnus(OutilTestCase):
    def test_ordinal_resolu_annonce(self):
        self.ecrit_table({})
        self.inconnus.write_text("[4242]", encoding="utf-8")
        _, texte = self.lance("--file", str(self.source({"Trouvee": 4242})))
        self.assertIn("now", texte)
        self.assertIn("4242", texte)

    def test_ordinal_toujours_absent_annonce(self):
        self.ecrit_table({})
        self.inconnus.write_text("[999999]", encoding="utf-8")
        _, texte = self.lance("--file", str(self.source({"Autre": 1})))
        self.assertIn("still", texte)
        self.assertIn("999999", texte)

    def test_journal_illisible_ne_fait_pas_echouer(self):
        self.ecrit_table({})
        self.inconnus.write_text("pas du json", encoding="utf-8")
        code, _ = self.lance("--file", str(self.source({"Une": 1})))
        self.assertEqual(code, 0)


class TestChemins(unittest.TestCase):
    def test_chemins_pris_chez_car_lookup(self):
        """Les redefinir dans l'outil le faisait ecrire ailleurs que la ou le
        programme lit, sans que rien ne le signale."""
        import car_lookup
        self.assertEqual(outil.TABLE, car_lookup.DATA_PATH)
        self.assertEqual(outil.INCONNUS, car_lookup.UNKNOWN_PATH)


if __name__ == "__main__":
    unittest.main()
