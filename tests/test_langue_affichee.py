"""Tout ce qui est AFFICHE doit etre en anglais.

Le projet a commence en francais ; la traduction s'est faite fichier par
fichier, et une chaine oubliee ne casse aucun test fonctionnel. Ce test la
detecte, la ou une relecture a la main finit toujours par en laisser passer.

Les commentaires et docstrings restent en francais (langue de travail de
l'auteur) : ils ne sont pas affiches, donc ils sont exclus de l'examen.
"""

import ast
import pathlib
import re
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[1]

# Marqueurs sans ambiguite : ces mots ne sont pas anglais. Volontairement
# court — mieux vaut un test qui ne crie pas au loup qu'un test qu'on
# desactive parce qu'il se plaint de "port" ou de "selection".
MOTS_FRANCAIS = re.compile(
    r"(?ix)\b(vehicule|voiture|canal|canaux|vitesse|regime|arreter|arrete|"
    r"demarrer|demarre|introuvable|aucun|aucune|lissage|lisse|fenetre|"
    r"ecoute|ecouter|reglage|reglages|afficher|masquer|quitter|ouvrir|"
    r"fermer|enregistrer|erreur|echec|cible|cibles|entree|sortie|"
    r"telemetrie|passerelle|jeu|paquet|paquets|trame|trames|"
    r"les|des|une|avec|pour|sans|dans|est|sont|pas|qui|que|mais|donc|"
    r"impossible|delai|apercu|actuelle|absente|absentes|conservees|"
    # vocabulaire d'unites : une unite traduite en francais ne contient
    # aucun des mots ci-dessus, la mutation "metres par seconde" passait.
    r"par|metre|metres|seconde|secondes|degre|degres|minute|minutes|"
    r"tour|tours|roue|roues|pneu|pneus|moteur|boite|essence|carburant|"
    r"gauche|droite|arriere|inconnu|inconnue|unite|unites|niveau|"
    r"nombre|hauteur|largeur|longueur|profondeur)\b")
ELISIONS = re.compile(r"(?i)\b[dlnqcjmst]'[a-z]")
ACCENTS = re.compile(r"[À-ſ]")


def suspecte(texte: str) -> str | None:
    """Renvoie le marqueur trouve, ou None."""
    for motif in (MOTS_FRANCAIS, ELISIONS, ACCENTS):
        trouve = motif.search(texte)
        if trouve:
            return trouve.group(0)
    return None


class TestTextesDesModules(unittest.TestCase):
    """Chaines litterales des modules, docstrings exclus."""

    FICHIERS = ["channel_catalog.py", "derived_channels.py", "smoothing.py",
                "osc_targets.py", "car_lookup.py", "tray.py", "bridge.py",
                "main.py", "gui.py", "ws_server.py", "http_assets.py",
                "tools/update_car_table.py", "cables/build_cables_patch.py"]

    @staticmethod
    def _chaines_hors_docstrings(chemin: pathlib.Path):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        docs = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
                if ast.get_docstring(noeud, clean=False) and noeud.body:
                    docs.add(id(noeud.body[0].value))
        for noeud in ast.walk(arbre):
            if (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
                    and id(noeud) not in docs):
                yield noeud.lineno, noeud.value

    def test_aucune_chaine_francaise(self):
        fautes = []
        for nom in self.FICHIERS:
            chemin = RACINE / nom
            for ligne, valeur in self._chaines_hors_docstrings(chemin):
                marqueur = suspecte(valeur)
                if marqueur:
                    fautes.append(f"{nom}:{ligne} ({marqueur!r}) {valeur!r}")
        self.assertEqual(fautes, [], "chaines francaises affichables :\n"
                         + "\n".join(fautes))


# Les unites forment un vocabulaire ferme et court. Le reperage par mots y
# est le plus faible (une unite traduite peut n'employer aucun mot courant),
# donc on verifie chaque mot contre cette liste. Ajouter une unite demande
# d'ajouter son vocabulaire ici : c'est voulu, c'est un acte delibere.
VOCABULAIRE_UNITES = {
    "awd", "compression", "cylinders", "deepest", "degc", "degf", "degrees",
    "dimensionless", "engaged", "extension", "fraction", "full", "fwd", "g",
    "gear", "grip", "h", "identifier", "index", "km", "lap", "left", "loss",
    "m", "mph", "ms", "n", "no", "normalised", "number", "pi", "position",
    "puddle",
    "rad", "redline", "reverse", "right", "rpm", "rwd", "s", "s1", "s2",
    "undocumented", "unknown", "w", "x",
}


# Les libelles courts (boutons, en-tetes, cadres, pastille d'etat, overlay)
# echappent au reperage par mots des qu'un mot francais ressemble a son
# equivalent anglais : "Recommande" pour "Recommended", "Accelerateur" pour
# "Throttle". Verifie par mutation. Leur vocabulaire est donc ferme, comme
# celui des unites : changer un libelle demande de l'ajouter ici.
VOCABULAIRE_INTERFACE = {
    "a", "active", "all", "apply", "brake", "bridge", "category",
    "changes", "channel", "channels", "clear", "comma", "computed",
    "connected", "connecting", "destinations", "differential", "enabled",
    "engine", "filter", "filtered", "forza", "forza/car_name", "from",
    "game", "horizon", "host", "hz", "input", "interrupted", "km/h",
    "local", "n", "network", "no", "none", "not", "number", "only", "open",
    "osc", "output", "overlay", "packets", "port", "racing", "rate",
    "recommended", "rpm", "s", "selection", "send", "separated",
    "smoothing", "start", "stationary", "stop", "stopped", "string",
    "telemetry", "the", "throttle", "to", "udp", "unit", "value", "vehicle",
    "websocket", "while",
}


def hors_vocabulaire(textes, vocabulaire) -> dict:
    """Mots absents du vocabulaire, avec le libelle qui les porte."""
    fautes = {}
    for texte in textes:
        for mot in re.findall(r"[A-Za-z][A-Za-z0-9_/]*", texte):
            if mot.lower() not in vocabulaire:
                fautes.setdefault(mot, texte)
    return fautes


class TestCatalogue(unittest.TestCase):
    def test_unites_dans_le_vocabulaire_attendu(self):
        from channel_catalog import UNITS
        inconnus = {}
        for canal, unite in UNITS.items():
            for mot in re.findall(r"[A-Za-z][A-Za-z0-9]*", unite):
                if mot.lower() not in VOCABULAIRE_UNITES:
                    inconnus.setdefault(mot, canal)
        self.assertEqual(inconnus, {},
                         "mots d'unite hors vocabulaire (traduction oubliee, "
                         "ou vocabulaire a completer) : "
                         + ", ".join(f"{m!r} ({c})" for m, c in inconnus.items()))

    def test_categories_et_unites_en_anglais(self):
        from channel_catalog import CATEGORIES, UNITS
        for categorie in CATEGORIES:
            with self.subTest(categorie=categorie):
                self.assertIsNone(suspecte(categorie))
        for canal, unite in UNITS.items():
            with self.subTest(canal=canal):
                self.assertIsNone(suspecte(unite), f"{canal}: {unite!r}")


class TestBarreSysteme(unittest.TestCase):
    def test_libelles_en_anglais(self):
        import tray
        for etat, libelle in tray.LABELS.items():
            with self.subTest(etat=etat):
                self.assertIsNone(suspecte(libelle), libelle)

    def test_libelles_dans_le_vocabulaire(self):
        import tray
        fautes = hors_vocabulaire(tray.LABELS.values(), VOCABULAIRE_INTERFACE)
        self.assertEqual(fautes, {}, f"mots inattendus : {fautes}")


class TestLigneDeCommande(unittest.TestCase):
    def test_aide_en_anglais(self):
        import main
        aide = main.build_parser().format_help()
        marqueur = suspecte(aide)
        self.assertIsNone(marqueur, f"--help contient {marqueur!r}")


class TestOverlay(unittest.TestCase):
    """Le HTML porte des commentaires francais ; seul le texte visible et les
    chaines injectees dans le DOM sont examines."""

    def setUp(self):
        self.source = (RACINE / "web" / "overlay.html").read_text(encoding="utf-8")

    def _sans_commentaires(self) -> str:
        s = re.sub(r"<!--.*?-->", "", self.source, flags=re.S)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        return re.sub(r"^\s*//.*$", "", s, flags=re.M)

    def test_texte_visible_en_anglais(self):
        corps = re.search(r"<body.*?</body>", self._sans_commentaires(),
                          flags=re.S).group(0)
        for texte in re.findall(r">([^<>{}]+)<", corps):
            texte = texte.strip()
            if texte:
                with self.subTest(texte=texte):
                    self.assertIsNone(suspecte(texte))

    def test_messages_injectes_en_anglais(self):
        code = self._sans_commentaires()
        for chaine in re.findall(r'"([^"\n]{4,})"', code):
            if chaine.startswith(("ws:", "http", "#", ".", "/")):
                continue
            with self.subTest(chaine=chaine):
                self.assertIsNone(suspecte(chaine))

    def test_titre_en_anglais(self):
        titre = re.search(r"<title>(.*?)</title>", self.source).group(1)
        self.assertIsNone(suspecte(titre))

    def test_libelles_visibles_dans_le_vocabulaire(self):
        """"Accelerateur" au lieu de "Throttle" ne contient aucun mot
        francais reperable : seul un vocabulaire ferme l'attrape."""
        corps = re.search(r"<body.*?</body>", self._sans_commentaires(),
                          flags=re.S).group(0)
        textes = [t.strip() for t in re.findall(r">([^<>{}]+)<", corps)
                  if t.strip()]
        titre = re.search(r"<title>(.*?)</title>", self.source).group(1)
        fautes = hors_vocabulaire(textes + [titre], VOCABULAIRE_INTERFACE)
        self.assertEqual(fautes, {}, f"mots inattendus : {fautes}")


class TestInterface(unittest.TestCase):
    """Tous les textes reellement portes par les widgets."""

    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:  # pragma: no cover
            self.skipTest("tkinter absent")
        import gui
        self.gui = gui
        self._config_origine = gui.CONFIG_PATH
        gui.CONFIG_PATH = pathlib.Path(__file__).with_name("_config_langue.json")
        if gui.CONFIG_PATH.exists():
            gui.CONFIG_PATH.unlink()
        try:
            self.root = tk.Tk()
        except tk.TclError:  # pragma: no cover
            self.skipTest("pas d'affichage disponible")
        self.app = gui.BridgeGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.app.tray = None
        self.app.bridge = None
        if self.app._refresh_id is not None:
            self.root.after_cancel(self.app._refresh_id)
        self.root.destroy()
        if self.gui.CONFIG_PATH.exists():
            self.gui.CONFIG_PATH.unlink()
        self.gui.CONFIG_PATH = self._config_origine

    def _textes(self):
        releve = [("<title>", self.root.title())]

        def descend(widget, chemin=""):
            classe = widget.winfo_class()
            ident = f"{chemin}/{classe}"
            if classe not in ("TEntry", "Entry"):
                try:
                    texte = widget.cget("text")
                except Exception:
                    texte = ""
                if isinstance(texte, str) and texte.strip():
                    releve.append((ident, texte))
            if classe == "Treeview":
                for colonne in widget.cget("columns"):
                    releve.append((ident, widget.heading(colonne, "text")))
            for enfant in widget.winfo_children():
                descend(enfant, ident)

        descend(self.root)
        for attribut in dir(self.app):
            if attribut.endswith("_var"):
                try:
                    valeur = getattr(self.app, attribut).get()
                except Exception:
                    continue
                if isinstance(valeur, str) and valeur.strip():
                    releve.append((attribut, valeur))
        return releve

    def test_tous_les_libelles_en_anglais(self):
        releve = self._textes()
        self.assertGreater(len(releve), 30, "releve suspicieusement court")
        for origine, texte in releve:
            with self.subTest(origine=origine, texte=texte):
                self.assertIsNone(suspecte(texte))

    def test_libelles_dans_le_vocabulaire(self):
        """"Recommande" pour "Recommended" passe tous les filtres par mots :
        les libelles courts sont donc verifies contre un vocabulaire ferme."""
        textes = [t for origine, t in self._textes()
                  if not origine.endswith("_var")]  # valeurs saisies exclues
        fautes = hors_vocabulaire(textes, VOCABULAIRE_INTERFACE)
        self.assertEqual(fautes, {}, "mots inattendus dans les libelles "
                         f"(traduction, ou vocabulaire a completer) : {fautes}")

    def test_messages_d_etat_en_anglais(self):
        """Les messages produits a l'execution ne sont pas dans les widgets au
        demarrage : on les declenche."""
        def etat_apres(action) -> str:
            action()
            self.root.update()
            texte = self.app.status_var.get()
            self.assertIsNone(suspecte(texte), texte)
            return texte

        # port invalide, destination OSC invalide : les deux refus les plus
        # frequents, et les seuls messages qu'on lit vraiment.
        self.app.listen_port_var.set("abc")
        self.assertIn("port", etat_apres(self.app._start_bridge).lower())

        self.app.listen_port_var.set("5300")
        # Saisie volontairement sans mot francais : le message la recopie,
        # et on veut examiner le message, pas l'entree.
        self.app.osc_targets_var.set("nope:")
        etat_apres(self.app._start_bridge)

        # lissage refuse sur un canal non lissable, puis efface
        self.app.smoothing_value_var.set("0.2")
        self.app.tree.selection_set([self.app.row_by_channel["gear"]])
        self.assertIn("gear", etat_apres(self.app._smooth_selection))
        etat_apres(self.app._clear_selection_smoothing)

        self.app.smoothing_value_var.set("xyz")
        etat_apres(self.app._smooth_selection)


if __name__ == "__main__":
    unittest.main()
