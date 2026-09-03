"""Logique de l'overlay, executee par node.

Le script de `web/overlay.html` n'etait couvert par aucun test : seul son texte
affiche etait examine. Et il n'est pas verifiable dans le navigateur integre —
un onglet non affiche ne compose aucune image, donc `requestAnimationFrame` ne
se declenche jamais et le DOM reste fige sur son etat initial.

`overlay_harness.mjs` charge donc le script REEL du fichier livre dans un
contexte `vm`, avec un DOM et un WebSocket simules et une horloge pilotee. Ce
test-ci ne fait que le lancer, pour que `python -m unittest discover` reste le
seul point d'entree.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
BANC = Path(__file__).with_name("overlay_harness.mjs")


class TestOverlay(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:  # pragma: no cover - depend de la machine
            self.skipTest("node absent : logique de l'overlay non verifiee")

    def test_banc_overlay(self):
        r = subprocess.run([self.node, str(BANC)], capture_output=True,
                           text=True, timeout=120, cwd=str(RACINE))
        self.assertEqual(r.returncode, 0,
                         "\n" + r.stdout + r.stderr)
        # Un banc qui n'executerait plus rien passerait au vert en silence.
        reussis = [l for l in r.stdout.splitlines() if "[ok]" in l]
        self.assertGreaterEqual(len(reussis), 20,
                                f"banc suspicieusement court :\n{r.stdout}")

    def test_le_banc_lit_bien_le_fichier_livre(self):
        """Contre-epreuve : si le banc testait une copie, modifier l'overlay ne
        changerait rien. On casse une chaine et on verifie que le banc tombe."""
        chemin = RACINE / "web" / "overlay.html"
        origine = chemin.read_text(encoding="utf-8")
        casse = origine.replace("Game idle — no packets received",
                                "Jeu au repos", 1)
        self.assertNotEqual(casse, origine, "chaine de reference introuvable")
        chemin.write_text(casse, encoding="utf-8")
        try:
            r = subprocess.run([self.node, str(BANC)], capture_output=True,
                               text=True, timeout=120, cwd=str(RACINE))
            self.assertNotEqual(r.returncode, 0,
                                "le banc n'a pas vu la modification : il ne lit "
                                "pas le fichier livre")
        finally:
            chemin.write_text(origine, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
