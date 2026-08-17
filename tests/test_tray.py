"""Icone de barre d'etat : logique d'etat et rendu de la pastille.

Le rendu dans la zone de notification elle-meme n'est pas verifiable
automatiquement ; ce qui l'est, c'est la deduction de l'etat et la
production de l'image.
"""

import unittest

import tray


class FauxPont:
    """Reproduit la surface de Bridge utilisee par l'interface."""

    def __init__(self, vivant=True, erreur=None, paquets=0, vitesse=0.0):
        self._vivant = vivant
        self.error = erreur
        self.packet_count = paquets
        self.listen_port = 5300
        self.latest_values = {"speed": vitesse}

    def is_alive(self):
        return self._vivant


class TestEtat(unittest.TestCase):
    def test_sans_pont(self):
        self.assertEqual(tray.etat_pont(None), tray.ARRETE)

    def test_erreur_prioritaire(self):
        pont = FauxPont(vivant=True, erreur="bind impossible", paquets=500)
        self.assertEqual(tray.etat_pont(pont), tray.ERREUR)

    def test_thread_mort_sans_message(self):
        self.assertEqual(tray.etat_pont(FauxPont(vivant=False)), tray.ERREUR)

    def test_aucun_paquet(self):
        self.assertEqual(tray.etat_pont(FauxPont(paquets=0)), tray.SANS_FLUX)

    def test_paquets_mais_vehicule_immobile(self):
        """Distinction reprise de la trame d'etat : des paquets qui arrivent
        sans rien faire varier ne sont PAS un flux mort."""
        pont = FauxPont(paquets=1000)
        self.assertEqual(tray.etat_pont(pont, en_mouvement=False), tray.EN_ATTENTE)

    def test_telemetrie_en_mouvement(self):
        pont = FauxPont(paquets=1000)
        self.assertEqual(tray.etat_pont(pont, en_mouvement=True), tray.ACTIF)

    def test_mouvement_inconnu_considere_actif(self):
        self.assertEqual(tray.etat_pont(FauxPont(paquets=10)), tray.ACTIF)


class TestPresentation(unittest.TestCase):
    def test_chaque_etat_a_une_couleur_et_un_libelle(self):
        for etat in (tray.ARRETE, tray.ERREUR, tray.SANS_FLUX,
                     tray.EN_ATTENTE, tray.ACTIF):
            with self.subTest(etat=etat):
                self.assertIn(etat, tray.COULEURS)
                self.assertIn(etat, tray.LIBELLES)

    def test_couleurs_distinctes(self):
        self.assertEqual(len(set(tray.COULEURS.values())), len(tray.COULEURS))

    def test_infobulle_mentionne_les_paquets(self):
        texte = tray.infobulle(tray.ACTIF, FauxPont(paquets=1234))
        self.assertIn("1234", texte)

    def test_infobulle_sans_pont(self):
        self.assertEqual(tray.infobulle(tray.ARRETE), tray.LIBELLES[tray.ARRETE])

    def test_image_produite(self):
        image = tray.image_icone(tray.ACTIF, taille=32)
        self.assertEqual(image.size, (32, 32))
        self.assertEqual(image.mode, "RGBA")

    def test_image_porte_la_couleur_de_l_etat(self):
        """Le pixel central doit etre celui de l'etat, sinon l'icone ne
        distinguerait rien."""
        for etat, couleur in tray.COULEURS.items():
            with self.subTest(etat=etat):
                image = tray.image_icone(etat, taille=64)
                self.assertEqual(image.getpixel((32, 32))[:3], couleur)

    def test_coins_transparents(self):
        image = tray.image_icone(tray.ACTIF, taille=64)
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
        return "#%02x%02x%02x" % tray.COULEURS[etat]

    def test_etat_initial_arrete(self):
        self.assertEqual(self._couleur(), self._hex(tray.ARRETE))
        self.assertEqual(self.app.state_var.get(), tray.LIBELLES[tray.ARRETE])

    def test_chaque_etat_a_sa_couleur(self):
        cas = [
            (FauxPont(paquets=0), 0.0, tray.SANS_FLUX),
            (FauxPont(paquets=500), 0.0, tray.EN_ATTENTE),
            (FauxPont(paquets=500), 30.0, tray.ACTIF),
            (FauxPont(paquets=500, erreur="panne"), 30.0, tray.ERREUR),
        ]
        for pont, vitesse, attendu in cas:
            with self.subTest(etat=attendu):
                pont.latest_values = {"speed": vitesse}
                self.app.bridge = pont
                self.app._refresh_state()
                self.root.update()
                self.assertEqual(self._couleur(), self._hex(attendu))
                self.assertEqual(self.app.state_var.get(), tray.LIBELLES[attendu])

    def test_detail_reste_distinct_du_libelle(self):
        """Le texte detaille (compteurs, erreurs) ne doit pas ecraser le
        libelle d'etat."""
        self.app.status_var.set("En ecoute sur le port 5300")
        self.root.update()
        self.assertEqual(self.app.state_var.get(), tray.LIBELLES[tray.ARRETE])


class TestDisponibilite(unittest.TestCase):
    def test_detection_des_dependances(self):
        icone = tray.TrayIcon(lambda: None, lambda: None, lambda: None, lambda: None)
        self.assertIsInstance(icone.disponible, bool)

    def test_update_sans_demarrage_ne_leve_pas(self):
        """L'interface appelle update() a chaque rafraichissement, y compris
        quand l'icone n'a pas pu demarrer."""
        icone = tray.TrayIcon(lambda: None, lambda: None, lambda: None, lambda: None)
        icone.update(tray.ACTIF, FauxPont(paquets=1))
        icone.stop()


if __name__ == "__main__":
    unittest.main()
