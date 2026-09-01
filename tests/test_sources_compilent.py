"""Chaque source Python du projet doit COMPILER, pas seulement s'analyser.

Defaut vecu : une constante placee avant `from __future__ import annotations`
rend le fichier inutilisable, mais `ast.parse` ne s'en plaint pas — c'est une
verification faite plus tard, a la compilation. Le test de langue, qui lit les
fichiers avec `ast`, a donc laisse passer un outil qui ne demarrait plus. Il est
reste casse jusqu'a ce qu'un test l'importe enfin.

Sont particulierement concernes les fichiers qu'aucun test n'importe, comme
l'outil d'entretien de la table des vehicules.
"""

import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def sources() -> list[Path]:
    fichiers = []
    for chemin in RACINE.rglob("*.py"):
        parties = set(chemin.parts)
        if "__pycache__" in parties or ".git" in parties:
            continue
        fichiers.append(chemin)
    return sorted(fichiers)


class TestCompilation(unittest.TestCase):
    def test_au_moins_tous_les_modules_attendus(self):
        """Garde-fou du garde-fou : si la collecte se vide, le test passerait
        au vert en ne verifiant plus rien."""
        noms = {c.name for c in sources()}
        for attendu in ("bridge.py", "gui.py", "main.py", "forza_telemetry.py",
                        "ws_server.py", "update_car_table.py"):
            with self.subTest(fichier=attendu):
                self.assertIn(attendu, noms)

    def test_chaque_source_compile(self):
        with tempfile.TemporaryDirectory() as dossier:
            for chemin in sources():
                with self.subTest(fichier=str(chemin.relative_to(RACINE))):
                    cible = Path(dossier) / (chemin.stem + ".pyc")
                    try:
                        py_compile.compile(str(chemin), cfile=str(cible),
                                           doraise=True)
                    except py_compile.PyCompileError as exc:
                        self.fail(f"{chemin.relative_to(RACINE)} ne compile "
                                  f"pas : {exc.msg.strip()}")


class TestOutilsExecutables(unittest.TestCase):
    """Un module peut s'importer et pourtant echouer lance en script."""

    def _aide(self, relatif: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RACINE / relatif), "--help"],
            capture_output=True, text=True, timeout=60, cwd=str(RACINE))

    def test_outil_table_des_vehicules(self):
        r = self._aide("tools/update_car_table.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--write", r.stdout)
        self.assertIn("--remove", r.stdout)

    def test_ligne_de_commande_principale(self):
        r = self._aide("main.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--osc", r.stdout)
        self.assertIn("--ws-port", r.stdout)


if __name__ == "__main__":
    unittest.main()
