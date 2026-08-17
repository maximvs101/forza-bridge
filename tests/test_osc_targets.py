"""Analyse des destinations OSC.

Ces cas correspondent a des defauts trouves en audit : chacun passait la
suite precedente, parce que les deux analyseurs dupliques n'avaient aucun
test.
"""

import unittest

from osc_targets import (DEFAULT_TARGET, InvalidTarget, format_target,
                         format_targets, parse_target, parse_targets)


class TestFormesValides(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(parse_target("127.0.0.1:7000"), ("127.0.0.1", 7000))

    def test_nom_d_hote(self):
        self.assertEqual(parse_target("studio-pc:9000"), ("studio-pc", 9000))

    def test_espaces_tolerees(self):
        self.assertEqual(parse_target("  127.0.0.1 : 7000  "), ("127.0.0.1", 7000))

    def test_ipv6_entre_crochets(self):
        self.assertEqual(parse_target("[::1]:7000"), ("::1", 7000))
        self.assertEqual(parse_target("[fe80::1]:9000"), ("fe80::1", 9000))

    def test_bornes_de_port(self):
        self.assertEqual(parse_target("h:1")[1], 1)
        self.assertEqual(parse_target("h:65535")[1], 65535)


class TestFormesRefusees(unittest.TestCase):
    def test_hote_vide(self):
        """Un hote vide etait accepte, puis `getaddrinfo('')` resolvait vers
        une interface locale et le premier envoi levait WinError 10049 —
        le pont mourait a la premiere trame."""
        with self.assertRaises(InvalidTarget):
            parse_target(":7000")

    def test_port_manquant(self):
        with self.assertRaises(InvalidTarget):
            parse_target("127.0.0.1")

    def test_port_non_numerique(self):
        with self.assertRaises(InvalidTarget):
            parse_target("127.0.0.1:abc")

    def test_exposant_unicode(self):
        """'²'.isdigit() vaut True mais int('²') leve : l'ancienne garde
        laissait echapper une ValueError nue au lieu d'un message."""
        with self.assertRaises(InvalidTarget):
            parse_target("127.0.0.1:²")

    def test_port_hors_plage(self):
        for texte in ("h:0", "h:65536", "h:99999", "h:-1"):
            with self.subTest(texte=texte):
                with self.assertRaises(InvalidTarget):
                    parse_target(texte)

    def test_ipv6_nu_refuse(self):
        """`rpartition` en tirerait l'hote `::` et le port 1 : une destination
        acceptee en silence vers un port que personne n'a demande."""
        with self.assertRaises(InvalidTarget):
            parse_target("::1")

    def test_ipv6_crochets_mal_formes(self):
        for texte in ("[::1]", "[::1:7000", "[::1]7000"):
            with self.subTest(texte=texte):
                with self.assertRaises(InvalidTarget):
                    parse_target(texte)

    def test_message_ne_suggere_pas_un_decoupage_faux(self):
        """Le message d'aide ne doit pas proposer la forme issue du mauvais
        decoupage (\"[:]:1\" pour \"::1\")."""
        with self.assertRaises(InvalidTarget) as contexte:
            parse_target("::1")
        self.assertNotIn("[:]", str(contexte.exception))


class TestListes(unittest.TestCase):
    def test_plusieurs_destinations(self):
        self.assertEqual(parse_targets("127.0.0.1:7000, 192.168.0.50:9000"),
                         [("127.0.0.1", 7000), ("192.168.0.50", 9000)])

    def test_point_virgule_accepte(self):
        self.assertEqual(len(parse_targets("a:1; b:2")), 2)

    def test_doublons_retires(self):
        """Deux fois la meme destination ouvrirait deux sockets et doublerait
        reellement le trafic vers le meme point d'arrivee."""
        self.assertEqual(parse_targets("127.0.0.1:7000, 127.0.0.1:7000"),
                         [("127.0.0.1", 7000)])

    def test_ordre_conserve(self):
        cibles = parse_targets("c:3, a:1, b:2")
        self.assertEqual(cibles, [("c", 3), ("a", 1), ("b", 2)])

    def test_liste_vide_refusee(self):
        for texte in ("", "   ", ",", " ; , "):
            with self.subTest(texte=texte):
                with self.assertRaises(InvalidTarget):
                    parse_targets(texte)

    def test_une_entree_invalide_rejette_tout(self):
        with self.assertRaises(InvalidTarget):
            parse_targets("127.0.0.1:7000, :9000")


class TestMiseEnForme(unittest.TestCase):
    def test_aller_retour(self):
        """La chaine enregistree par l'interface doit etre recopiable en
        ligne de commande : les deux analyseurs precedents divergeaient."""
        for texte in ("127.0.0.1:7000",
                      "127.0.0.1:7000, 192.168.0.50:9000",
                      "[::1]:7000, studio:9000"):
            with self.subTest(texte=texte):
                cibles = parse_targets(texte)
                self.assertEqual(parse_targets(format_targets(cibles)), cibles)

    def test_ipv6_remis_entre_crochets(self):
        self.assertEqual(format_target(("::1", 7000)), "[::1]:7000")

    def test_ipv4_sans_crochets(self):
        self.assertEqual(format_target(("127.0.0.1", 7000)), "127.0.0.1:7000")

    def test_defaut_analysable(self):
        self.assertEqual(parse_target(format_target(DEFAULT_TARGET)),
                         DEFAULT_TARGET)


if __name__ == "__main__":
    unittest.main()
