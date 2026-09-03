"""Mise en page de la fenetre : rien ne doit etre tronque.

Le defaut d'origine : une taille codee en dur, relevee sur une machine
donnee, coupait les libelles en largeur et poussait la barre d'etat hors
cadre. Un test qui verifie une CONSTANTE (1120x820) n'aurait rien prouve,
puisque c'est justement la constante qui etait fausse. On verifie donc le
rapport entre la fenetre et ce que son contenu demande.
"""

import pathlib
import unittest


class LayoutTestCase(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:  # pragma: no cover - tkinter absent
            self.skipTest("tkinter absent")
        import gui
        self.tk = tk
        self.gui = gui
        self._config_origine = gui.CONFIG_PATH
        gui.CONFIG_PATH = pathlib.Path(__file__).with_name("_config_layout.json")
        if gui.CONFIG_PATH.exists():
            gui.CONFIG_PATH.unlink()
        try:
            self.root = tk.Tk()
        except tk.TclError:  # pragma: no cover - pas d'affichage
            self.skipTest("pas d'affichage disponible")
        self.app = gui.BridgeGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.app.tray = None
        self.app.bridge = None
        if self.app._refresh_id is not None:
            self.root.after_cancel(self.app._refresh_id)
        self.root.destroy()
        if self.gui.CONFIG_PATH.exists():
            self.gui.CONFIG_PATH.unlink()
        self.gui.CONFIG_PATH = self._config_origine

    def _besoin(self) -> tuple[int, int]:
        self.root.update_idletasks()
        return self.root.winfo_reqwidth(), self.root.winfo_reqheight()


class TestDimensionnement(LayoutTestCase):
    def test_fenetre_au_moins_aussi_grande_que_son_contenu(self):
        besoin_l, besoin_h = self._besoin()
        largeur, hauteur = self.gui.size_window(self.root)
        self.assertGreaterEqual(largeur, besoin_l)
        self.assertGreaterEqual(hauteur, besoin_h)

    def test_minsize_couvre_le_contenu(self):
        """Reduire la fenetre a son minimum ne doit rien cacher : c'est ce qui
        faisait disparaitre la barre d'etat."""
        besoin_l, besoin_h = self._besoin()
        self.gui.size_window(self.root)
        mini_l, mini_h = self.root.minsize()
        self.assertGreaterEqual(mini_l, besoin_l)
        self.assertGreaterEqual(mini_h, besoin_h)

    def test_place_supplementaire_pour_le_tableau(self):
        """Sans marge, la fenetre serre le tableau a la hauteur d'une poignee
        de lignes alors que c'est la zone utile."""
        _, besoin_h = self._besoin()
        _, hauteur = self.gui.size_window(self.root, extra_rows=14)
        self.assertGreater(hauteur, besoin_h,
                           "le tableau des canaux n'a aucune place en plus")

    def test_reste_dans_l_ecran(self):
        self.gui.size_window(self.root, extra_rows=400)  # demande absurde
        largeur, hauteur = (int(x) for x in
                            self.root.geometry().split("+")[0].split("x"))
        self.assertLessEqual(largeur, self.root.winfo_screenwidth())
        self.assertLessEqual(hauteur, self.root.winfo_screenheight())


class TestBarreDEtat(LayoutTestCase):
    def test_barre_d_etat_visible_au_minimum(self):
        self.gui.size_window(self.root)
        mini_l, mini_h = self.root.minsize()
        self.root.geometry(f"{mini_l}x{mini_h}")
        self.root.update_idletasks()
        self.root.update()
        barre = self.app.state_canvas.master
        bas = barre.winfo_y() + barre.winfo_height()
        self.assertLessEqual(bas, self.root.winfo_height(),
                             "la barre d'etat sort de la fenetre")

    def test_barre_d_etat_sous_le_tableau(self):
        """Empaquetee apres le tableau extensible, elle se faisait pousser
        dehors ; elle doit l'etre AVANT, donc rester en bas."""
        self.gui.size_window(self.root)
        self.root.update_idletasks()
        self.root.update()
        barre = self.app.state_canvas.master
        self.assertGreater(barre.winfo_y(), self.app.tree.winfo_y())


class TestTableauDesCanaux(LayoutTestCase):
    def test_tous_les_canaux_sont_listes(self):
        from channel_catalog import ALL_CHANNELS
        self.assertEqual(len(self.app.row_by_channel), len(ALL_CHANNELS))

    def test_colonnes_dans_l_ordre_attendu(self):
        self.assertEqual(tuple(self.app.tree.cget("columns")),
                         ("send", "channel", "category", "unit",
                          "smoothing", "value"))

    def test_selection_multiple_possible(self):
        """Le lissage s'applique a la selection : sans mode etendu, on ne
        pourrait le regler qu'un canal a la fois."""
        self.assertEqual(str(self.app.tree.cget("selectmode")), "extended")

    def test_aucun_libelle_vide(self):
        for colonne in self.app.tree.cget("columns"):
            with self.subTest(colonne=colonne):
                self.assertTrue(self.app.tree.heading(colonne, "text").strip())


if __name__ == "__main__":
    unittest.main()
