"""Icone de barre d'etat : logique d'etat et rendu de la pastille.

Le rendu dans la zone de notification elle-meme n'est pas verifiable
automatiquement ; ce qui l'est, c'est la deduction de l'etat et la
production de l'image.
"""

import unittest

import tray


class FauxPont:
    """Reproduit la surface de Bridge utilisee par l'interface."""

    def __init__(self, alive=True, error=None, packets=0, speed=0.0):
        self._alive = alive
        self.error = error
        self.packet_count = packets
        self.listen_port = 5300
        self.latest_values = {"speed": speed}

    def is_alive(self):
        return self._alive


class TestEtat(unittest.TestCase):
    def test_sans_pont(self):
        self.assertEqual(tray.bridge_state(None), tray.STOPPED)

    def test_erreur_prioritaire(self):
        pont = FauxPont(alive=True, error="bind impossible", packets=500)
        self.assertEqual(tray.bridge_state(pont), tray.FAILED)

    def test_thread_mort_sans_message(self):
        self.assertEqual(tray.bridge_state(FauxPont(alive=False)), tray.FAILED)

    def test_aucun_paquet(self):
        self.assertEqual(tray.bridge_state(FauxPont(packets=0)), tray.NO_DATA)

    def test_paquets_mais_vehicule_immobile(self):
        """Distinction reprise de la trame d'etat : des paquets qui arrivent
        sans rien faire varier ne sont PAS un flux mort."""
        pont = FauxPont(packets=1000)
        self.assertEqual(tray.bridge_state(pont, moving=False), tray.IDLE)

    def test_telemetrie_en_mouvement(self):
        pont = FauxPont(packets=1000)
        self.assertEqual(tray.bridge_state(pont, moving=True), tray.ACTIVE)

    def test_mouvement_inconnu_considere_actif(self):
        self.assertEqual(tray.bridge_state(FauxPont(packets=10)), tray.ACTIVE)


class TestPresentation(unittest.TestCase):
    def test_chaque_etat_a_une_couleur_et_un_libelle(self):
        for etat in (tray.STOPPED, tray.FAILED, tray.NO_DATA,
                     tray.IDLE, tray.ACTIVE):
            with self.subTest(etat=etat):
                self.assertIn(etat, tray.COLOURS)
                self.assertIn(etat, tray.LABELS)

    def test_couleurs_distinctes(self):
        self.assertEqual(len(set(tray.COLOURS.values())), len(tray.COLOURS))

    def test_tooltip_mentionne_les_paquets(self):
        texte = tray.tooltip(tray.ACTIVE, FauxPont(packets=1234))
        self.assertIn("1234", texte)

    def test_tooltip_sans_pont(self):
        self.assertEqual(tray.tooltip(tray.STOPPED), tray.LABELS[tray.STOPPED])

    def test_image_produite(self):
        image = tray.icon_image(tray.ACTIVE, size=32)
        self.assertEqual(image.size, (32, 32))
        self.assertEqual(image.mode, "RGBA")

    def test_image_porte_la_couleur_de_l_etat(self):
        """Le pixel central doit etre celui de l'etat, sinon l'icone ne
        distinguerait rien."""
        for etat, couleur in tray.COLOURS.items():
            with self.subTest(etat=etat):
                image = tray.icon_image(etat, size=64)
                self.assertEqual(image.getpixel((32, 32))[:3], couleur)

    def test_coins_transparents(self):
        image = tray.icon_image(tray.ACTIVE, size=64)
        self.assertEqual(image.getpixel((0, 0))[3], 0)


class TestIndicateurDansLaFenetre(unittest.TestCase):
    """La pastille de la fenetre et celle de la barre systeme sont pilotees
    par le meme calcul d'etat : elles ne peuvent pas se contredire."""

    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("tkinter absent")
        import pathlib
        import gui
        self._gui = gui
        self._config_origine = gui.CONFIG_PATH
        gui.CONFIG_PATH = pathlib.Path(__file__).with_name("_config_test.json")
        if gui.CONFIG_PATH.exists():
            gui.CONFIG_PATH.unlink()
        self.root = tk.Tk()
        self.app = gui.BridgeGUI(self.root)
        self.root.update()

    def tearDown(self):
        self.app.tray = None  # evite de toucher a la barre systeme
        self.app.bridge = None
        if self.app._refresh_id is not None:
            self.root.after_cancel(self.app._refresh_id)
        self.root.destroy()
        if self._gui.CONFIG_PATH.exists():
            self._gui.CONFIG_PATH.unlink()
        self._gui.CONFIG_PATH = self._config_origine

    def _couleur(self) -> str:
        return self.app.state_canvas.itemcget(self.app.state_dot, "fill")

    @staticmethod
    def _hex(etat: str) -> str:
        return "#%02x%02x%02x" % tray.COLOURS[etat]

    def test_etat_initial_arrete(self):
        self.assertEqual(self._couleur(), self._hex(tray.STOPPED))
        self.assertEqual(self.app.state_var.get(), tray.LABELS[tray.STOPPED])

    def test_chaque_etat_a_sa_couleur(self):
        cas = [
            (FauxPont(packets=0), 0.0, tray.NO_DATA),
            (FauxPont(packets=500), 0.0, tray.IDLE),
            (FauxPont(packets=500), 30.0, tray.ACTIVE),
            (FauxPont(packets=500, error="panne"), 30.0, tray.FAILED),
        ]
        for pont, vitesse, attendu in cas:
            with self.subTest(etat=attendu):
                pont.latest_values = {"speed": vitesse}
                self.app.bridge = pont
                self.app._refresh_state()
                self.root.update()
                self.assertEqual(self._couleur(), self._hex(attendu))
                self.assertEqual(self.app.state_var.get(), tray.LABELS[attendu])

    def test_detail_reste_distinct_du_libelle(self):
        """Le texte detaille (compteurs, erreurs) ne doit pas ecraser le
        libelle d'etat."""
        self.app.status_var.set("En ecoute sur le port 5300")
        self.root.update()
        self.assertEqual(self.app.state_var.get(), tray.LABELS[tray.STOPPED])


class TestDisponibilite(unittest.TestCase):
    def test_detection_des_dependances(self):
        icone = tray.TrayIcon(lambda: None, lambda: None, lambda: None, lambda: None)
        self.assertIsInstance(icone.available, bool)

    def test_update_sans_demarrage_ne_leve_pas(self):
        """L'interface appelle update() a chaque rafraichissement, y compris
        quand l'icone n'a pas pu demarrer."""
        icone = tray.TrayIcon(lambda: None, lambda: None, lambda: None, lambda: None)
        icone.update(tray.ACTIVE, FauxPont(packets=1))
        icone.stop()


if __name__ == "__main__":
    unittest.main()
