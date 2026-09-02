"""Trois defauts trouves en relecture, chacun verrouille par un test.

Ils partagent un trait : le programme continuait de fonctionner en apparence.
Un thread mort remplace par un message d'erreur, une destination annoncee en
panne alors qu'elle repond, un indicateur qui envoie chercher un probleme
inexistant. Aucun ne cassait un test existant.
"""

import socket
import threading
import time
import unittest

import tray
from bridge import Bridge
from tests.helpers import OscRecorder, free_port, make_packet, wait_until
from ws_server import TelemetryWebSocketServer


def envoie(port: int, packet: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
    finally:
        sock.close()


class TestBoucleFermeePendantPublication(unittest.TestCase):
    """`publish()` lisait `self._loop`, puis s'en servait plus loin.

    `stop()` ferme la boucle asyncio AVANT de remettre `_loop` a None : dans
    cet intervalle l'appel levait `RuntimeError: Event loop is closed`.
    L'exception remontait dans la boucle du pont, ou `except BaseException`
    la capturait — et le thread mourait. Le declencheur reel : decocher la
    case WebSocket pendant que le jeu emet.
    """

    def setUp(self):
        self.serveur = TelemetryWebSocketServer(host="127.0.0.1",
                                                port=free_port(),
                                                rate_hz=1000.0)
        self.assertTrue(self.serveur.start(), self.serveur.error)
        self.boucle = self.serveur._loop
        # publish() sort tot si personne n'ecoute : un client fictif suffit,
        # le test porte sur la planification, pas sur l'envoi.
        self.serveur._clients.add(object())

    def tearDown(self):
        self.serveur.stop()

    def test_boucle_fermee_ne_leve_pas(self):
        self.serveur.stop()
        self.assertTrue(self.boucle.is_closed())
        # Etat exact de la course : la boucle est fermee mais l'attribut
        # n'a pas encore ete remis a None.
        self.serveur._loop = self.boucle

        try:
            resultat = self.serveur.publish({"speed": 1.0})
        except BaseException as exc:  # noqa: BLE001 - c'est ce qu'on interdit
            self.fail(f"publish a leve {type(exc).__name__}: {exc}")
        self.assertFalse(resultat,
                         "aucune trame ne peut partir sur une boucle fermee")

    def test_trame_perdue_comptee(self):
        """Perdre une trame a l'arret est acceptable ; le taire ne l'est pas."""
        self.serveur.stop()
        self.serveur._loop = self.boucle
        avant = self.serveur.dropped_count
        self.serveur.publish({"speed": 1.0})
        self.assertEqual(self.serveur.dropped_count, avant + 1)

    def test_le_pont_survit_a_l_arret_du_serveur(self):
        """Contre-epreuve par le vrai chemin : le pont publie pendant que le
        serveur s'arrete, et doit rester vivant."""
        port = free_port()
        pont = Bridge(listen_port=port, osc_clients=[OscRecorder()],
                      selected_channels=frozenset({"speed"}),
                      ws_server=self.serveur)
        self.addCleanup(pont.join, 3)
        self.addCleanup(pont.stop)
        pont.start()
        self.assertTrue(pont.bound.wait(5))

        arret = threading.Event()

        def trafic():
            while not arret.is_set():
                envoie(port, make_packet(speed=30.0))
                time.sleep(0.002)

        fil = threading.Thread(target=trafic, daemon=True)
        fil.start()
        try:
            wait_until(lambda: pont.packet_count >= 5)
            self.serveur.stop()
            time.sleep(0.2)
        finally:
            arret.set()
            fil.join(timeout=2)

        self.assertTrue(pont.is_alive(), f"thread mort : {pont.error}")
        self.assertIsNone(pont.error)


class ClientIntermittent:
    """Echoue les `echecs` premiers envois, puis fonctionne."""

    def __init__(self, echecs: int = 1):
        self.echecs = echecs
        self.envois = 0

    def send(self, message):
        if self.echecs > 0:
            self.echecs -= 1
            raise OSError("[WinError 10051] reseau injoignable")
        self.envois += 1


class TestPanneOscEffaceeAuRetablissement(unittest.TestCase):
    """`osc_failures` n'etait jamais vide : un seul hoquet marquait la
    destination en panne pour toute la session. La barre d'etat affichait
    alors "FAILED" en permanence, et une vraie panne ne s'en distinguait plus.
    """

    def _pont(self, client, cible=("10.0.0.1", 9000)):
        port = free_port()
        pont = Bridge(listen_port=port, osc_clients=[client],
                      osc_targets=[cible],
                      selected_channels=frozenset({"speed"}))
        self.addCleanup(pont.join, 3)
        self.addCleanup(pont.stop)
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        return port, pont

    def test_echec_passager_efface_par_un_envoi_reussi(self):
        client = ClientIntermittent(echecs=1)
        port, pont = self._pont(client)
        for _ in range(10):
            envoie(port, make_packet(speed=30.0))
            time.sleep(0.005)
        wait_until(lambda: client.envois >= 3)

        self.assertEqual(pont.osc_failures, {},
                         "la panne est restee affichee apres retablissement")

    def test_panne_persistante_reste_signalee(self):
        """Contre-epreuve : sans elle, un `osc_failures.clear()` systematique
        passerait le test precedent tout en masquant les vraies pannes."""
        client = ClientIntermittent(echecs=10 ** 6)
        port, pont = self._pont(client, cible=("10.0.0.2", 9001))
        for _ in range(3):
            envoie(port, make_packet(speed=30.0))
        wait_until(lambda: pont.osc_failures)

        self.assertIn(("10.0.0.2", 9001), pont.osc_failures)
        self.assertIn("10051", pont.osc_failures[("10.0.0.2", 9001)])


class TestIndicateurAvecSeulementEnCourse(unittest.TestCase):
    """Avec "seulement en course", `packet_count` restait a 0 en menu et
    l'indicateur annoncait "No packets from the game" — le message qui envoie
    verifier Data Out, alors que le jeu emet normalement.
    """

    def _pont(self, only_racing=True):
        port = free_port()
        pont = Bridge(listen_port=port, osc_clients=[OscRecorder()],
                      selected_channels=frozenset({"speed"}),
                      only_racing=only_racing)
        self.addCleanup(pont.join, 3)
        self.addCleanup(pont.stop)
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        return port, pont

    def test_paquets_filtres_comptes_comme_recus(self):
        port, pont = self._pont()
        for _ in range(5):
            envoie(port, make_packet(is_race_on=0, speed=0.0))
        wait_until(lambda: pont.received_count >= 5)

        self.assertGreaterEqual(pont.received_count, 5)
        self.assertEqual(pont.packet_count, 0,
                         "les trames filtrees ne doivent pas etre emises")

    def test_etat_annonce_le_jeu_connecte(self):
        """Ni NO_DATA (le jeu emet), ni ACTIVE (rien ne part) : l'etat dit
        que le filtre retient tout."""
        port, pont = self._pont()
        for _ in range(5):
            envoie(port, make_packet(is_race_on=0, speed=0.0))
        wait_until(lambda: pont.received_count >= 5)

        etat = tray.bridge_state(pont, moving=False)
        self.assertEqual(etat, tray.FILTERED, tray.LABELS.get(etat))
        self.assertNotEqual(etat, tray.NO_DATA)

    def test_aucun_paquet_reste_no_data(self):
        """Contre-epreuve : le correctif ne doit pas rendre NO_DATA
        inatteignable, sinon un jeu reellement muet passerait inapercu."""
        _, pont = self._pont()
        self.assertEqual(pont.received_count, 0)
        self.assertEqual(tray.bridge_state(pont, moving=False), tray.NO_DATA)

    def test_trame_d_etat_distingue_les_deux_compteurs(self):
        port, pont = self._pont()
        for _ in range(5):
            envoie(port, make_packet(is_race_on=0, speed=0.0))
        wait_until(lambda: pont.received_count >= 5)

        etat = pont.status()
        self.assertGreaterEqual(etat["packets_received"], 5)
        self.assertEqual(etat["packets"], 0)


if __name__ == "__main__":
    unittest.main()
