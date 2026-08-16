"""Service de fichiers statiques greffe sur le port WebSocket."""

import socket
import unittest

from tests.helpers import free_port
from ws_server import TelemetryWebSocketServer
import http_assets


class TestResolution(unittest.TestCase):
    def test_racine_sert_l_index(self):
        cible = http_assets._resolve("/")
        self.assertIsNotNone(cible)
        self.assertEqual(cible.name, http_assets.INDEX)

    def test_fichier_existant(self):
        self.assertIsNotNone(http_assets._resolve("/overlay.html"))

    def test_parametres_ignores(self):
        self.assertIsNotNone(http_assets._resolve("/overlay.html?port=8765#ancre"))

    def test_fichier_absent(self):
        self.assertIsNone(http_assets._resolve("/inexistant.html"))

    def test_remontee_de_repertoire_refusee(self):
        """Seul web/ est expose : rien du projet ne doit fuir."""
        for chemin in ("/../config.json", "/../car_ordinals.json",
                       "/../../.claude/settings.local.json",
                       "/web/../../main.py", "/./../main.py"):
            with self.subTest(chemin=chemin):
                self.assertIsNone(http_assets._resolve(chemin))


class TestServiHttp(unittest.TestCase):
    """Requetes brutes : un client HTTP normalise les chemins avant l'envoi et
    testerait donc autre chose que la protection reelle."""

    @classmethod
    def setUpClass(cls):
        cls.serveur = TelemetryWebSocketServer(
            host="127.0.0.1", port=free_port(socket.SOCK_STREAM), serve_assets=True)
        assert cls.serveur.start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.stop()

    def get(self, chemin: str) -> tuple[int, bytes]:
        sock = socket.create_connection(("127.0.0.1", self.serveur.port), timeout=5)
        try:
            sock.sendall(f"GET {chemin} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                         f"Connection: close\r\n\r\n".encode())
            data = b""
            while True:
                bloc = sock.recv(4096)
                if not bloc:
                    break
                data += bloc
        finally:
            sock.close()
        entete, _, corps = data.partition(b"\r\n\r\n")
        code = int(entete.split()[1])
        return code, corps

    def test_index(self):
        code, corps = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<html", corps.lower())

    def test_type_de_contenu(self):
        sock = socket.create_connection(("127.0.0.1", self.serveur.port), timeout=5)
        try:
            sock.sendall(b"GET /overlay.html HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            entete = sock.recv(4096).split(b"\r\n\r\n")[0].lower()
        finally:
            sock.close()
        self.assertIn(b"text/html", entete)

    def test_absent(self):
        code, _ = self.get("/inexistant.html")
        self.assertEqual(code, 404)

    def test_traversees_refusees(self):
        for chemin in ("/../config.json", "/..%2fconfig.json",
                       "/%2e%2e/config.json", "/web/../../main.py",
                       "//etc/passwd", "/../../.claude/settings.local.json"):
            with self.subTest(chemin=chemin):
                code, corps = self.get(chemin)
                self.assertEqual(code, 404)
                self.assertNotIn(b"listen_port", corps)
                self.assertNotIn(b"import", corps)


if __name__ == "__main__":
    unittest.main()
