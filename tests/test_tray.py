"""Icone de barre d'etat : logique d'etat et rendu de la pastille.

Le rendu dans la zone de notification elle-meme n'est pas verifiable
automatiquement ; ce qui l'est, c'est la deduction de l'etat et la
production de l'image.
"""

import unittest

import tray


class FauxPont:
    def __init__(self, vivant=True, erreur=None, paquets=0):
        self._vivant = vivant
        self.error = erreur
        self.packet_count = paquets

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
