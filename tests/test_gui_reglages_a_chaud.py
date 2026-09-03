"""Reglages modifiables pont en marche, et commandes qui ne mentent pas.

Defaut d'origine, constate par l'utilisateur : cocher "Enabled" dans le cadre
WebSocket pendant que le pont tournait ne faisait RIEN — la case n'avait pas de
`command`, sa valeur n'etait lue qu'au demarrage — et aucun message ne le
signalait. Meme silence pour "Only while racing" et "Computed channels".

Regle retenue : ce qui peut s'appliquer a chaud s'applique a chaud ; ce qui
exige une reconstruction est GRISE pendant la marche.
"""

import logging
import pathlib
import socket
import unittest

from tests.helpers import free_port

# La sonde d'ecoute ouvre une connexion TCP et la ferme sans poignee de main
# HTTP : `websockets` journalise alors une trace sans rapport avec le test.
logging.getLogger("websockets").setLevel(logging.CRITICAL)


class FauxPont:
    """Surface du Bridge utilisee par l'interface. Les quatre attributs
    concernes sont relus a chaque paquet par la vraie boucle, ce qui rend le
    changement a chaud possible."""

    def __init__(self):
        self.ws_server = None
        self.only_racing = False
        self.derived = True
        self.send_car_name = True
        self.error = None
        self.packet_count = 0
        self.listen_port = 5300
        self.latest_values = {}
        self.arrete = False

    def is_alive(self):
        return not self.arrete

    def stop(self):
        self.arrete = True

    def join(self, timeout=None):
        pass

    # Le vrai pont fournit le contenu de l'accueil et de la trame d'etat : le
    # faux doit exposer la meme surface, sinon il validerait une interface qui
    # oublie de les brancher. TestServeurBrancheAuVraiPont verifie le contrat
    # lui-meme, avec un vrai Bridge.
    def hello(self):
        return {"type": "hello", "channels": ["speed"]}

    def status(self):
        return {"packets": self.packet_count}

    def attach_ws_server(self, ws_server):
        self.ws_server = ws_server
        if ws_server is not None:
            ws_server.hello_factory = self.hello
            ws_server.status_factory = self.status


class ReglagesTestCase(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:  # pragma: no cover
            self.skipTest("tkinter absent")
        import gui
        self.gui = gui
        self._config_origine = gui.CONFIG_PATH
        gui.CONFIG_PATH = pathlib.Path(__file__).with_name("_config_chaud.json")
        if gui.CONFIG_PATH.exists():
            gui.CONFIG_PATH.unlink()
        try:
            self.root = tk.Tk()
        except tk.TclError:  # pragma: no cover
            self.skipTest("pas d'affichage disponible")
        self.app = gui.BridgeGUI(self.root)
        self.app.tray = None
        self.root.update_idletasks()

    def tearDown(self):
        self.app.tray = None
        self.app._stop_ws()
        self.app.bridge = None
        if self.app._refresh_id is not None:
            self.root.after_cancel(self.app._refresh_id)
        self.root.destroy()
        if self.gui.CONFIG_PATH.exists():
            self.gui.CONFIG_PATH.unlink()
        self.gui.CONFIG_PATH = self._config_origine

    def _ecoute(self, port: int) -> bool:
        with socket.socket() as s:
            s.settimeout(2)
            return s.connect_ex(("127.0.0.1", port)) == 0


class TestWebSocketAChaud(ReglagesTestCase):
    def test_cocher_demarre_vraiment_le_serveur(self):
        port = free_port()
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()

        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())
        self.assertTrue(self._ecoute(port), "le port n'accepte pas de connexion")
        self.assertIs(self.app.bridge.ws_server, self.app.ws_server,
                      "le pont ne connait pas le serveur : il ne publierait rien")
        self.assertIn(str(port), self.app.status_var.get())

    def test_decocher_arrete_et_detache(self):
        port = free_port()
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertTrue(self._ecoute(port))

        self.app.ws_enabled_var.set(False)
        self.app._on_ws_enabled_toggled()
        self.assertIsNone(self.app.ws_server)
        self.assertIsNone(self.app.bridge.ws_server,
                          "le pont publierait vers un serveur arrete")
        self.assertFalse(self._ecoute(port), "le port reste ouvert")

    def test_pont_arrete_ne_demarre_rien(self):
        """Sans pont, la case ne fait que memoriser le choix : demarrer un
        serveur orphelin laisserait un port ouvert sans personne pour publier."""
        self.app.bridge = None
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNone(self.app.ws_server)

    def test_echec_de_demarrage_decoche_la_case(self):
        """Une case cochee alors que le serveur n'a pas demarre annoncerait un
        service inexistant."""
        occupe = socket.socket()
        occupe.bind(("127.0.0.1", 0))
        occupe.listen(1)
        port = occupe.getsockname()[1]
        try:
            self.app.bridge = FauxPont()
            self.app.ws_port_var.set(str(port))
            self.app.ws_enabled_var.set(True)
            self.app._on_ws_enabled_toggled()

            self.assertIsNone(self.app.ws_server)
            self.assertFalse(self.app.ws_enabled_var.get())
            self.assertIn("WebSocket", self.app.status_var.get())
        finally:
            occupe.close()

    def test_port_invalide_signale(self):
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set("abc")
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNone(self.app.ws_server)
        self.assertFalse(self.app.ws_enabled_var.get())
        self.assertIn("port", self.app.status_var.get().lower())


class TestAutresReglagesAChaud(ReglagesTestCase):
    def test_only_racing_applique_immediatement(self):
        pont = self.app.bridge = FauxPont()
        self.app.only_racing_var.set(True)
        self.app._on_only_racing_toggled()
        self.assertTrue(pont.only_racing)
        self.app.only_racing_var.set(False)
        self.app._on_only_racing_toggled()
        self.assertFalse(pont.only_racing)

    def test_canaux_derives_appliques_immediatement(self):
        pont = self.app.bridge = FauxPont()
        self.app.derived_var.set(False)
        self.app._on_derived_toggled()
        self.assertFalse(pont.derived)

    def test_sans_pont_aucune_erreur(self):
        self.app.bridge = None
        self.app._on_only_racing_toggled()
        self.app._on_derived_toggled()


class TestCommandesGrisees(ReglagesTestCase):
    @staticmethod
    def _desactive(widget) -> bool:
        return "disabled" in str(widget.cget("state"))

    def test_tout_actif_a_l_arret(self):
        for widget in self.app._restart_widgets + self.app._ws_widgets:
            with self.subTest(widget=widget.winfo_class()):
                self.assertFalse(self._desactive(widget))

    def test_port_et_destinations_grises_en_marche(self):
        """Ces deux champs reconstruisent le socket d'ecoute et les clients
        OSC : les laisser actifs faisait croire a un changement applique."""
        self.app.bridge = FauxPont()
        self.app._refresh_controls()
        for widget in self.app._restart_widgets:
            with self.subTest(widget=widget.winfo_class()):
                self.assertTrue(self._desactive(widget))

    def test_reglages_websocket_grises_quand_le_serveur_tourne(self):
        port = free_port()
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())
        for widget in self.app._ws_widgets:
            with self.subTest(widget=widget.winfo_class()):
                self.assertTrue(self._desactive(widget))

    def test_reglages_websocket_rendus_apres_arret(self):
        """Decocher doit rendre les champs modifiables, sinon on ne pourrait
        plus jamais changer le port sans quitter l'application."""
        port = free_port()
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.app.ws_enabled_var.set(False)
        self.app._on_ws_enabled_toggled()
        for widget in self.app._ws_widgets:
            with self.subTest(widget=widget.winfo_class()):
                self.assertFalse(self._desactive(widget))

    def test_champs_rendus_apres_arret_du_pont(self):
        self.app.bridge = FauxPont()
        self.app._refresh_controls()
        self.app._stop_bridge()
        for widget in self.app._restart_widgets:
            with self.subTest(widget=widget.winfo_class()):
                self.assertFalse(self._desactive(widget))


class TestClicReel(ReglagesTestCase):
    """Passe par le WIDGET, pas par la methode.

    Les tests ci-dessus appellent `_on_ws_enabled_toggled()` directement : ils
    ne prouvent donc pas qu'un CLIC y mene. `invoke()` fait ce que fait un
    clic — basculer la variable et appeler la commande — donc une case mal
    cablee echoue ici, ce qui est exactement le defaut constate par
    l'utilisateur.
    """

    def _case(self, libelle: str):
        trouvee = []

        def descend(widget):
            if (widget.winfo_class() == "TCheckbutton"
                    and str(widget.cget("text")) == libelle):
                trouvee.append(widget)
            for enfant in widget.winfo_children():
                descend(enfant)

        descend(self.root)
        self.assertEqual(len(trouvee), 1, f"case {libelle!r} introuvable")
        return trouvee[0]

    def test_clic_sur_enabled_demarre_puis_arrete_le_serveur(self):
        port = free_port()
        self.app.bridge = FauxPont()
        self.app.ws_port_var.set(str(port))
        self.app.ws_enabled_var.set(False)
        case = self._case("Enabled")

        case.invoke()                       # premier clic : on coche
        self.assertTrue(self.app.ws_enabled_var.get())
        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())
        self.assertTrue(self._ecoute(port), "le clic n'a pas ouvert le port")
        self.assertIs(self.app.bridge.ws_server, self.app.ws_server)

        case.invoke()                       # second clic : on decoche
        self.assertFalse(self.app.ws_enabled_var.get())
        self.assertIsNone(self.app.ws_server)
        self.assertFalse(self._ecoute(port), "le port est reste ouvert")

    def test_clic_sur_only_racing_atteint_le_pont(self):
        pont = self.app.bridge = FauxPont()
        self.app.only_racing_var.set(False)
        self._case("Only while racing").invoke()
        self.assertTrue(pont.only_racing)

    def test_clic_sur_canaux_derives_atteint_le_pont(self):
        pont = self.app.bridge = FauxPont()
        self.app.derived_var.set(True)
        self._case("Computed channels").invoke()
        self.assertFalse(pont.derived)

    def test_clic_sur_le_bouton_start_bascule_le_libelle(self):
        """Le bouton doit annoncer l'action suivante, pas l'etat courant."""
        self.assertEqual(str(self.app.start_button.cget("text")), "Start")
        self.app.bridge = FauxPont()
        self.app.start_button.configure(text="Stop")
        self.app.start_button.invoke()       # declenche _toggle_bridge -> stop
        self.assertIsNone(self.app.bridge)
        self.assertEqual(str(self.app.start_button.cget("text")), "Start")


class TestServeurBrancheAuVraiPont(ReglagesTestCase):
    """Avec un VRAI Bridge, et un vrai client.

    Defaut trouve en essayant l'interface sur le jeu, pas par ces tests : un
    serveur demarre a chaud n'avait pas les fabriques du message d'accueil ni
    de la trame d'etat — elles n'etaient posees que dans le constructeur du
    pont. L'accueil annoncait 0 canal, aucun vehicule, `packets: null`, alors
    que la telemetrie circulait normalement. Un faux pont ne pouvait pas le
    voir : il n'a pas de fabriques.
    """

    def _vrai_pont(self):
        from bridge import Bridge
        from tests.helpers import OscRecorder
        pont = Bridge(listen_port=free_port(), osc_clients=[OscRecorder()],
                      selected_channels=frozenset({"speed", "gear"}))
        self.addCleanup(pont.join, 3)
        self.addCleanup(pont.stop)
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        return pont

    def test_fabriques_posees_au_demarrage_a_chaud(self):
        pont = self.app.bridge = self._vrai_pont()
        self.app.ws_port_var.set(str(free_port()))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())

        serveur = self.app.ws_server
        self.assertEqual(serveur.hello_factory, pont.hello,
                         "message d'accueil sans contenu : 0 canal annonce")
        self.assertEqual(serveur.status_factory, pont.status,
                         "trame d'etat sans compteurs")

    def test_accueil_reellement_rempli(self):
        """Le critere qui compte : ce que recoit un client."""
        pont = self.app.bridge = self._vrai_pont()
        self.app.ws_port_var.set(str(free_port()))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.assertIsNotNone(self.app.ws_server, self.app.status_var.get())

        accueil = self.app.ws_server.hello_factory()
        self.assertGreater(len(accueil.get("channels", [])), 0,
                           "aucun canal annonce a l'accueil")
        self.assertIn("speed", accueil["channels"])
        etat = self.app.ws_server.status_factory()
        self.assertIn("packets", etat)

    def test_detache_a_l_arret(self):
        pont = self.app.bridge = self._vrai_pont()
        self.app.ws_port_var.set(str(free_port()))
        self.app.ws_enabled_var.set(True)
        self.app._on_ws_enabled_toggled()
        self.app.ws_enabled_var.set(False)
        self.app._on_ws_enabled_toggled()
        self.assertIsNone(pont.ws_server,
                          "le pont publierait vers un serveur arrete")


class TestCablageDesCases(ReglagesTestCase):
    """Contre-epreuve du defaut : une case sans `command` compilait et passait
    tous les tests fonctionnels. On verifie donc le cablage lui-meme."""

    def _cases(self):
        trouvees = {}

        def descend(widget):
            if widget.winfo_class() == "TCheckbutton":
                trouvees[str(widget.cget("text"))] = widget
            for enfant in widget.winfo_children():
                descend(enfant)

        descend(self.root)
        return trouvees

    def test_cases_a_effet_immediat_ont_une_commande(self):
        cases = self._cases()
        for libelle in ("Enabled", "Only while racing", "Computed channels"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, cases)
                self.assertTrue(str(cases[libelle].cget("command")),
                                f"la case {libelle!r} n'appelle rien : "
                                "elle serait sans effet pont en marche")


if __name__ == "__main__":
    unittest.main()
