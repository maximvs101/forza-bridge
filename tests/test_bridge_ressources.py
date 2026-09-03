"""Deux defauts latents du pont, tous deux invisibles a l'usage normal.

  - `_emit` se servait de `_clients_by_target`, etabli seulement par `run()` :
    l'appeler avant le demarrage levait AttributeError au lieu de ne rien
    faire ;
  - les clients OSC construits par le pont n'etaient jamais fermes. Chaque
    cycle Start/Stop laissait un socket UDP ouvert jusqu'au ramasse-miettes,
    ce qu'un ResourceWarning signalait pendant les tests d'interface.

Un troisieme soupcon s'est revele FAUX a la mesure, et le test le fige pour
qu'on ne le "corrige" pas par exces de prudence : copier un dict pendant
qu'un autre thread y insere n'est pas une course, `dict()` ne relachant pas
le GIL.
"""

import gc
import threading
import time
import unittest
import warnings

from bridge import Bridge
from tests.helpers import OscRecorder, free_port


class TestEmissionAvantDemarrage(unittest.TestCase):
    def test_emit_avant_run_ne_leve_pas(self):
        pont = Bridge(listen_port=free_port(), osc_clients=[OscRecorder()])
        try:
            pont._emit("/forza/speed", 1.0)
        except AttributeError as exc:
            self.fail(f"_emit avant demarrage : {exc}")

    def test_rien_n_est_emis_avant_demarrage(self):
        """Contre-epreuve : ne pas lever ne doit pas vouloir dire emettre
        vers des destinations qui n'existent pas encore."""
        recorder = OscRecorder()
        pont = Bridge(listen_port=free_port(), osc_clients=[recorder])
        pont._emit("/forza/speed", 1.0)
        self.assertEqual(recorder.messages, [])


class TestFermetureDesClients(unittest.TestCase):
    """`SimpleUDPClient` expose un `close()` public : rien n'oblige a laisser
    le ramasse-miettes s'en charger."""

    def _pont_demarre(self, **kwargs):
        pont = Bridge(listen_port=free_port(),
                      osc_targets=[("127.0.0.1", free_port())], **kwargs)
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        self.assertIsNone(pont.error)
        return pont

    def test_sockets_fermes_a_l_arret(self):
        pont = self._pont_demarre()
        clients = list(pont.osc_clients)
        self.assertTrue(clients, "aucun client construit")
        self.assertTrue(all(c._sock.fileno() != -1 for c in clients),
                        "les sockets devraient etre ouverts en marche")

        pont.stop()
        pont.join(timeout=3)
        self.assertFalse(pont.is_alive())

        for client in clients:
            # `fileno() == -1` est la marque d'un socket ferme.
            self.assertEqual(client._sock.fileno(), -1,
                             "socket OSC laisse ouvert apres l'arret")

    def test_fermeture_meme_si_le_port_est_pris(self):
        """Un port d'ecoute deja occupe faisait sortir run() avant le
        `finally` : les sockets OSC restaient ouverts."""
        occupe = free_port()
        premier = Bridge(listen_port=occupe,
                         osc_targets=[("127.0.0.1", free_port())])
        premier.start()
        self.assertTrue(premier.bound.wait(5))
        self.addCleanup(premier.join, 3)
        self.addCleanup(premier.stop)

        second = Bridge(listen_port=occupe,
                        osc_targets=[("127.0.0.1", free_port())])
        second.start()
        self.assertTrue(second.bound.wait(5))
        second.join(timeout=3)
        self.assertIsNotNone(second.error, "le bind aurait du echouer")

        for client in second.osc_clients:
            self.assertEqual(client._sock.fileno(), -1,
                             "socket OSC laisse ouvert apres un bind refuse")

    def test_clients_injectes_non_touches(self):
        """Contre-epreuve : les clients fournis par l'appelant lui
        appartiennent. Les fermer casserait un test qui les reutilise, ou une
        integration qui partage un client entre deux ponts."""
        class ClientFermable:
            def __init__(self):
                self.ferme = False

            def send(self, message):
                pass

            def close(self):
                self.ferme = True

        client = ClientFermable()
        pont = Bridge(listen_port=free_port(), osc_clients=[client])
        pont.start()
        self.assertTrue(pont.bound.wait(5))
        pont.stop()
        pont.join(timeout=3)

        self.assertFalse(client.ferme,
                         "le pont a ferme un client qu'il n'a pas ouvert")

    def test_aucun_avertissement_de_ressource(self):
        """Le symptome d'origine : ResourceWarning au ramasse-miettes."""
        with warnings.catch_warnings(record=True) as releve:
            warnings.simplefilter("always", ResourceWarning)
            pont = self._pont_demarre()
            pont.stop()
            pont.join(timeout=3)
            del pont
            gc.collect()

        sockets = [w for w in releve
                   if issubclass(w.category, ResourceWarning)
                   and "socket" in str(w.message)]
        self.assertEqual(sockets, [], f"sockets non fermes : "
                                      f"{[str(w.message) for w in sockets]}")


class TestCopieDeDictNonConcurrente(unittest.TestCase):
    """Soupcon INFIRME par la mesure, fige ici pour ne pas etre "corrige".

    `status()` copie `rejected_sizes` depuis le thread WebSocket pendant que
    la boucle du pont y insere. J'y ai vu une course ; elle n'existe pas :
    `dict(autre_dict)` est un chemin C qui ne relache pas le GIL, donc aucun
    thread ne peut s'intercaler. Deux secondes de martelage avec des cles
    neuves ne produisent aucune erreur.
    """

    def test_copie_pendant_insertion(self):
        pont = Bridge(listen_port=free_port(), osc_clients=[OscRecorder()])
        arret = threading.Event()
        erreurs = []

        def inserteur():
            n = 0
            while not arret.is_set():
                pont.rejected_count += 1
                pont.rejected_sizes[n % 4096] = 1
                n += 1

        def lecteur():
            while not arret.is_set():
                try:
                    pont.status()
                except Exception as exc:  # noqa: BLE001
                    erreurs.append(f"{type(exc).__name__}: {exc}")
                    return

        fils = [threading.Thread(target=inserteur, daemon=True),
                threading.Thread(target=lecteur, daemon=True)]
        for fil in fils:
            fil.start()
        time.sleep(0.5)
        arret.set()
        for fil in fils:
            fil.join(timeout=2)

        self.assertEqual(erreurs, [], "la copie de dict n'est plus atomique : "
                                      "il faudrait alors un verrou")


if __name__ == "__main__":
    unittest.main()
