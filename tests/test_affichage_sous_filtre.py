"""Ce que l'interface montre pendant que "seulement en course" filtre.

Constate par l'utilisateur, jeu en marche : le filtre fonctionnait — les deux
compteurs divergeaient bien — mais l'AFFICHAGE mentait. `latest_values`
n'etait mis a jour qu'APRES le filtre, donc :

  - le tableau des canaux restait fige sur la derniere trame en course, et
    montrait une vitesse d'il y a plusieurs minutes comme si elle etait
    courante ;
  - l'indicateur en deduisait "Telemetry active" alors que plus rien ne
    partait ;
  - `is_race_on` de la trame d'etat restait bloque a vrai, puisqu'il est lu
    dans `latest_values`.

Le filtre porte sur ce qui est EMIS, pas sur ce qui est AFFICHE.
"""

import socket
import time
import unittest

import tray
from bridge import Bridge
from tests.helpers import OscRecorder, free_port, make_packet, wait_until


def envoie(port: int, packet: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
    finally:
        sock.close()


class FiltreTestCase(unittest.TestCase):
    def _pont(self, only_racing=True, **kwargs):
        port = free_port()
        pont = Bridge(listen_port=port, osc_clients=[OscRecorder()],
                      selected_channels=frozenset({"speed"}),
                      only_racing=only_racing, **kwargs)
        self.addCleanup(pont.join, 3)
        self.addCleanup(pont.stop)
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        return port, pont

    def _roule(self, port, pont, vitesse=40.0, combien=10):
        avant = pont.packet_count
        for _ in range(combien):
            envoie(port, make_packet(is_race_on=1, speed=vitesse))
            time.sleep(0.003)
        wait_until(lambda: pont.packet_count >= avant + combien)

    def _menu(self, port, pont, combien=20):
        avant = pont.received_count
        for _ in range(combien):
            envoie(port, make_packet(is_race_on=0, speed=0.0))
            time.sleep(0.003)
        wait_until(lambda: pont.received_count >= avant + combien)
        time.sleep(0.15)


class TestAffichageSuitLeJeu(FiltreTestCase):
    def test_valeurs_non_figees_sur_la_derniere_course(self):
        port, pont = self._pont()
        self._roule(port, pont, vitesse=40.0)
        self.assertAlmostEqual(pont.latest_values["speed"], 40.0, places=3)

        self._menu(port, pont)
        self.assertAlmostEqual(pont.latest_values["speed"], 0.0, places=3,
                               msg="le tableau reste fige sur la derniere "
                                   "trame en course")

    def test_is_race_on_de_la_trame_d_etat_suit(self):
        """Il est lu dans `latest_values` : bloque apres le filtre, il
        annoncait une course en cours depuis le menu."""
        port, pont = self._pont()
        self._roule(port, pont)
        self.assertTrue(pont.status()["is_race_on"])

        self._menu(port, pont)
        self.assertFalse(pont.status()["is_race_on"])

    def test_canaux_derives_presents_meme_filtres(self):
        """L'affichage montre les canaux calcules comme les bruts, sinon la
        moitie du tableau se viderait des l'entree dans un menu."""
        port, pont = self._pont(derived=True)
        self._menu(port, pont)
        self.assertIn("speed_kmh", pont.latest_values)
        self.assertAlmostEqual(pont.latest_values["speed_kmh"], 0.0, places=3)

    def test_rien_n_est_emis_pour_autant(self):
        """Contre-epreuve : mettre a jour l'affichage ne doit pas relacher le
        filtre, sinon l'option ne servirait plus a rien."""
        port, pont = self._pont()
        self._menu(port, pont)
        self.assertEqual(pont.packet_count, 0)
        self.assertGreaterEqual(pont.received_count, 20)


class TestEtatFiltre(FiltreTestCase):
    def test_filtre_actif_annonce(self):
        port, pont = self._pont()
        self._roule(port, pont)
        self._menu(port, pont)

        etat = tray.bridge_state(pont, moving=False)
        self.assertEqual(etat, tray.FILTERED, tray.LABELS.get(etat))
        self.assertEqual(tray.LABELS[etat], "Game connected, not racing")

    def test_pas_d_etat_actif_quand_rien_ne_part(self):
        """Le defaut constate : "Telemetry active" alors que le filtre retient
        tout. `moving=True` vient de la vitesse retenue de la derniere
        course."""
        port, pont = self._pont()
        self._roule(port, pont, vitesse=40.0)
        self._menu(port, pont)
        self.assertNotEqual(tray.bridge_state(pont, moving=True), tray.ACTIVE)

    def test_retour_en_course_redevient_actif(self):
        port, pont = self._pont()
        self._menu(port, pont)
        self.assertEqual(tray.bridge_state(pont, moving=False), tray.FILTERED)

        self._roule(port, pont, vitesse=40.0)
        self.assertEqual(tray.bridge_state(pont, moving=True), tray.ACTIVE)

    def test_sans_l_option_une_voiture_arretee_reste_idle(self):
        """Contre-epreuve : FILTERED ne doit pas avaler IDLE. Sans l'option,
        une voiture a l'arret en course reste "vehicle stationary"."""
        port, pont = self._pont(only_racing=False)
        for _ in range(10):
            envoie(port, make_packet(is_race_on=0, speed=0.0))
        wait_until(lambda: pont.packet_count >= 10)
        self.assertEqual(tray.bridge_state(pont, moving=False), tray.IDLE)

    def test_couleur_distincte(self):
        couleurs = [tray.COLOURS[e] for e in
                    (tray.STOPPED, tray.FAILED, tray.NO_DATA, tray.FILTERED,
                     tray.IDLE, tray.ACTIVE)]
        self.assertEqual(len(set(couleurs)), len(couleurs))


class TestLissageNonPollueParLeFiltre(FiltreTestCase):
    """Le lissage porte sur le flux EMIS. L'appliquer aux trames filtrees
    ferait glisser son etat vers les zeros du menu, et la reprise partirait
    d'une valeur fausse."""

    def test_etat_du_lissage_intact_apres_un_passage_en_menu(self):
        port, pont = self._pont(smoothing_settings={"speed": 0.2})
        self._roule(port, pont, vitesse=40.0, combien=40)
        lisse_avant = pont.latest_values.get("speed_smooth")
        self.assertIsNotNone(lisse_avant)

        self._menu(port, pont, combien=40)
        self.assertAlmostEqual(pont.smoother._state["speed"], lisse_avant,
                               places=6,
                               msg="le lissage a derive sur des trames filtrees")


if __name__ == "__main__":
    unittest.main()
