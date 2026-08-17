"""Diffusion OSC vers plusieurs destinations.

Cette surface n'avait aucun test : les 180 tests au vert donnaient une
fausse assurance sur la fonctionnalite principale du commit qui l'a
introduite.
"""

import socket
import unittest

from bridge import Bridge, _osc_type
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_message import OscMessage
from tests.helpers import OscRecorder, free_port, make_packet, wait_until


def envoie(port: int, packet: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
    finally:
        sock.close()


class FanoutTestCase(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.bridge = None

    def tearDown(self):
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge.join(timeout=3)

    def demarre(self, clients, **kwargs) -> Bridge:
        self.bridge = Bridge(listen_port=self.port, osc_clients=clients,
                             selected_channels=frozenset({"speed"}), **kwargs)
        self.bridge.start()
        self.assertTrue(self.bridge.bound.wait(5))
        self.assertIsNone(self.bridge.error)
        return self.bridge


class TestDiffusion(FanoutTestCase):
    def test_toutes_les_destinations_recoivent(self):
        a, b, c = OscRecorder(), OscRecorder(), OscRecorder()
        self.demarre([a, b, c])
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: all(r.messages for r in (a, b, c)))

        for recorder in (a, b, c):
            self.assertIn("/forza/speed", recorder.addresses)

    def test_valeurs_identiques_partout(self):
        a, b = OscRecorder(), OscRecorder()
        self.demarre([a, b])
        envoie(self.port, make_packet(speed=42.5))
        wait_until(lambda: a.messages and b.messages)

        vitesses_a = [v for adr, v in a.messages if adr == "/forza/speed"]
        vitesses_b = [v for adr, v in b.messages if adr == "/forza/speed"]
        self.assertEqual(vitesses_a, vitesses_b)


class TestIsolationDesPannes(FanoutTestCase):
    """Sans isolation, une seule destination injoignable tuait le thread et
    arretait aussi toutes les autres ET la diffusion WebSocket."""

    class ClientCasse:
        def __init__(self):
            self.tentatives = 0

        def send(self, message):
            self.tentatives += 1
            raise OSError("[WinError 10051] reseau injoignable")

    def test_une_panne_n_arrete_pas_les_autres(self):
        casse, sain = self.ClientCasse(), OscRecorder()
        self.demarre([casse, sain])
        for _ in range(3):
            envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: self.bridge.packet_count >= 3)
        wait_until(lambda: len(sain.messages) >= 3)

        self.assertTrue(self.bridge.is_alive(), f"thread mort: {self.bridge.error}")
        self.assertIsNone(self.bridge.error)
        self.assertIn("/forza/speed", sain.addresses)

    def test_panne_signalee_sans_arreter(self):
        casse, sain = self.ClientCasse(), OscRecorder()
        pont = self.demarre([casse, sain],
                            osc_targets=[("casse", 1), ("sain", 2)])
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: pont.osc_failures)

        self.assertIn(("casse", 1), pont.osc_failures)
        self.assertNotIn(("sain", 2), pont.osc_failures)
        self.assertIn("10051", pont.osc_failures[("casse", 1)])

    def test_la_panne_n_empeche_pas_les_suivantes(self):
        """Si la boucle s'arretait a la premiere erreur, les destinations
        situees apres ne recevraient jamais cette trame."""
        casse, sain = self.ClientCasse(), OscRecorder()
        self.demarre([casse, sain])  # la cassee est en PREMIER
        envoie(self.port, make_packet(speed=30.0))
        wait_until(lambda: sain.messages)
        self.assertTrue(sain.messages)


class TestTypeOsc(unittest.TestCase):
    """python-osc encode tout flottant Python en `f` (32 bits) : convertir un
    grand entier en float perdait plus de precision que l'etiquette `h`
    qu'on cherchait a eviter."""

    @staticmethod
    def _aller_retour(valeur):
        constructeur = OscMessageBuilder(address="/t")
        impose = _osc_type(valeur)
        if impose is None:
            constructeur.add_arg(valeur)
        else:
            constructeur.add_arg(float(valeur), arg_type=impose)
        return OscMessage(constructeur.build().dgram).params[0]

    def test_entiers_dans_int32_restent_entiers(self):
        for valeur in (0, -1, 100, 2 ** 31 - 1, -(2 ** 31)):
            with self.subTest(valeur=valeur):
                self.assertIsNone(_osc_type(valeur))
                self.assertEqual(self._aller_retour(valeur), valeur)

    def test_entiers_hors_int32_gardent_leur_valeur_exacte(self):
        for valeur in (2 ** 31, 3000000007, 4294967295):
            with self.subTest(valeur=valeur):
                self.assertEqual(_osc_type(valeur),
                                 OscMessageBuilder.ARG_TYPE_DOUBLE)
                self.assertEqual(self._aller_retour(valeur), valeur,
                                 "un double doit rendre l'entier exact")

    def test_un_float32_aurait_perdu_la_valeur(self):
        """Contre-epreuve : sans type impose, la valeur serait degradee."""
        constructeur = OscMessageBuilder(address="/t")
        constructeur.add_arg(float(3000000007))
        degrade = OscMessage(constructeur.build().dgram).params[0]
        self.assertNotEqual(degrade, 3000000007)

    def test_flottants_et_booleens_inchanges(self):
        self.assertIsNone(_osc_type(3.5))
        self.assertIsNone(_osc_type(True))


class TestPrecisionParLeVraiChemin(FanoutTestCase):
    """Les tests ci-dessus reconstruisent le message eux-memes, donc ils ne
    verifient PAS que le pont l'encode ainsi : une mutation de `_emet` leur
    echappait. Celui-ci passe par la boucle reelle.
    """

    def test_timestamp_hors_int32_arrive_exact(self):
        grand = 3000000007  # `timestamp_ms` depasse 2^31 apres ~24,8 jours
        recorder = OscRecorder()
        self.bridge = Bridge(listen_port=self.port, osc_clients=[recorder],
                             selected_channels=frozenset({"timestamp_ms"}),
                             derived=False)
        self.bridge.start()
        self.assertTrue(self.bridge.bound.wait(5))
        envoie(self.port, make_packet(timestamp_ms=grand))
        wait_until(lambda: any(a == "/forza/timestamp_ms"
                               for a, _ in recorder.messages))

        recus = [v for a, v in recorder.messages if a == "/forza/timestamp_ms"]
        self.assertEqual(recus[-1], grand,
                         "encode en float32, la valeur serait degradee")


class TestConstruction(unittest.TestCase):
    def test_doublons_retires(self):
        pont = Bridge(listen_port=free_port(),
                      osc_targets=[("127.0.0.1", 7000), ("127.0.0.1", 7000)],
                      osc_clients=[OscRecorder()])
        self.assertEqual(pont.osc_targets, [("127.0.0.1", 7000)])

    def test_osc_targets_reflete_la_demande(self):
        """L'ancien attribut annoncait la valeur par defaut alors que des
        clients injectes emettaient ailleurs."""
        cibles = [("10.0.0.1", 8000), ("10.0.0.2", 8001)]
        pont = Bridge(listen_port=free_port(), osc_targets=cibles,
                      osc_clients=[OscRecorder(), OscRecorder()])
        self.assertEqual(pont.osc_targets, cibles)

    def test_liste_vide_refusee(self):
        """Une liste explicitement vide ne doit pas devenir localhost."""
        with self.assertRaises(ValueError):
            Bridge(listen_port=free_port(), osc_targets=[])

    def test_hote_irresolvable_signale_sans_lever(self):
        """La resolution a lieu dans le thread du pont : une erreur remonte
        par `error`, elle ne s'echappe plus du constructeur (ce qui laissait
        le serveur WebSocket orphelin dans l'interface)."""
        pont = Bridge(listen_port=free_port(),
                      osc_targets=[("hote-qui-n-existe-pas.invalid", 7000)])
        pont.start()
        self.assertTrue(pont.bound.wait(15))
        pont.join(timeout=3)
        self.assertIsNotNone(pont.error)
        self.assertIn("no reachable OSC destination", pont.error)


if __name__ == "__main__":
    unittest.main()
