"""Ce que l'interface dit doit rester lisible, et ne doit pas mentir.

Deux defauts jumeaux, tous deux invisibles pour les tests existants parce
qu'ils portaient sur la DUREE et la VERACITE de l'affichage, pas sur son
contenu :

  - la barre d'etat est reecrite toutes les 150 ms pendant la marche, si bien
    que tout retour d'action disparaissait avant d'avoir pu etre lu — mesure :
    un message pose pont en marche avait disparu 600 ms plus tard. Le README
    promet pourtant que les canaux non lissables sont NOMMES plutot que
    silencieusement ignores ;
  - le bouton "Open overlay" ouvrait l'URL meme serveur arrete : le navigateur
    affichait une erreur de connexion, sans rapport apparent avec la case a
    cocher qui en est la cause.
"""

import pathlib
import time
import unittest

from tests.helpers import free_port


class InterfaceTestCase(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:  # pragma: no cover
            self.skipTest("tkinter absent")
        import gui
        self.gui = gui
        self._config_origine = gui.CONFIG_PATH
        gui.CONFIG_PATH = pathlib.Path(__file__).with_name("_config_messages.json")
        if gui.CONFIG_PATH.exists():
            gui.CONFIG_PATH.unlink()
        try:
            self.root = tk.Tk()
        except tk.TclError:  # pragma: no cover
            self.skipTest("pas d'affichage disponible")
        self.app = gui.BridgeGUI(self.root)
        self.app.tray = None
        # Aucun navigateur ne doit s'ouvrir pendant les tests.
        self._ouvertures = []
        self._open_origine = gui.webbrowser.open
        gui.webbrowser.open = self._ouvertures.append
        self.root.update_idletasks()

    def tearDown(self):
        self.gui.webbrowser.open = self._open_origine
        self.app.tray = None
        if self.app.bridge is not None:
            self.app._stop_bridge()
        self.app._stop_ws()
        if self.app._refresh_id is not None:
            self.root.after_cancel(self.app._refresh_id)
        self.root.destroy()
        if self.gui.CONFIG_PATH.exists():
            self.gui.CONFIG_PATH.unlink()
        self.gui.CONFIG_PATH = self._config_origine

    def _demarre_le_pont(self):
        self.app.listen_port_var.set(str(free_port()))
        self.app.ws_enabled_var.set(False)
        self.app._start_bridge()
        self.assertIsNotNone(self.app.bridge, self.app.status_var.get())
        self.root.update()

    def _laisse_tourner(self, secondes: float) -> None:
        """Fait tourner la boucle tkinter, comme le ferait mainloop()."""
        fin = time.perf_counter() + secondes
        while time.perf_counter() < fin:
            self.root.update()
            time.sleep(0.02)


class TestMessageLisible(InterfaceTestCase):
    def test_un_message_survit_au_rafraichissement(self):
        self._demarre_le_pont()
        self.app._flash("MESSAGE IMPORTANT")
        self._laisse_tourner(0.6)      # 4 tours de boucle
        self.assertEqual(self.app.status_var.get(), "MESSAGE IMPORTANT")

    def test_le_message_finit_par_ceder_la_place(self):
        """Contre-epreuve : un message qui reste pour toujours masquerait les
        compteurs, ce qui serait le defaut inverse."""
        self._demarre_le_pont()
        self.app._flash("MESSAGE IMPORTANT", seconds=0.2)
        self._laisse_tourner(0.6)
        self.assertIn("packets", self.app.status_var.get())

    def test_canal_non_lissable_reellement_annonce(self):
        """Le README promet que les canaux refuses sont nommes. Avant, le
        message existait mais disparaissait en 150 ms."""
        self._demarre_le_pont()
        self.app.smoothing_value_var.set("0.2")
        self.app.tree.selection_set([self.app.row_by_channel["gear"]])
        self.app._smooth_selection()
        self._laisse_tourner(0.5)

        texte = self.app.status_var.get()
        self.assertIn("gear", texte)
        self.assertIn("Skipped", texte)

    def test_erreur_de_port_websocket_reste_affichee(self):
        """Cas reel : la case WebSocket est cochee pont en marche avec un port
        invalide. Sans echeance, l'utilisateur ne voyait jamais pourquoi."""
        self._demarre_le_pont()
        self.app.ws_port_var.set("abc")
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self._laisse_tourner(0.5)

        self.assertIn("port", self.app.status_var.get().lower())


class TestBoutonOverlay(InterfaceTestCase):
    def test_serveur_arrete_n_ouvre_rien(self):
        self.assertIsNone(self.app.ws_server)
        self.app._open_overlay()
        self.assertEqual(self._ouvertures, [],
                         "une page d'erreur de connexion a ete ouverte")

    def test_serveur_arrete_explique_pourquoi(self):
        self.app._open_overlay()
        texte = self.app.status_var.get()
        self.assertIn("WebSocket", texte)
        self.assertIn("Start", texte)      # pont arrete : il faut demarrer

    def test_pont_en_marche_indique_la_case(self):
        self._demarre_le_pont()
        self.app._open_overlay()
        self.assertIn("Enabled", self.app.status_var.get())

    def test_serveur_en_marche_ouvre_le_bon_port(self):
        """Le port du serveur REELLEMENT en ecoute, pas le champ de saisie :
        les deux different tant que le serveur n'a pas ete redemarre."""
        self._demarre_le_pont()
        port = free_port()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())

        # Le champ est modifie apres coup : l'URL ne doit pas le suivre.
        self.app.ws_port_var.set("9999")
        self.app._open_overlay()

        self.assertEqual(self._ouvertures, [f"http://localhost:{port}/"])

    def test_la_fenetre_revient_au_premier_plan(self):
        """Le bouton existe aussi dans la barre systeme : fenetre repliee, le
        message serait invisible et le clic sans effet apparent."""
        self.root.withdraw()
        self.root.update()
        self.app._open_overlay()
        self.root.update()
        self.assertEqual(self.root.state(), "normal")


if __name__ == "__main__":
    unittest.main()
