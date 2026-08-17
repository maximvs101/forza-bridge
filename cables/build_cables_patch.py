"""Generateur de patches cables.gl (.cables) branches sur la passerelle Forza.

Un patch de cables standalone est du JSON ordinaire sur disque, d'extension
`.cables`. Le schema a ete releve sur un patch reel enregistre par le logiciel,
pas deduit d'une documentation.

Format, tel qu'observe :
  - Un op vaut {opId, id, attribs, uiAttribs, portsIn, portsOut}.
  - `opId` est l'UUID du TYPE d'op, stable et public (depot cables-gl/cables,
    fichier src/ops/base/<Op>/<Op>.json, champ "id"). `id` designe l'INSTANCE.
  - Les ports serialises sont des SURCHARGES, pas des declarations : l'op
    definit lui-meme ses ports au chargement. On n'ecrit donc que ce que l'on
    fixe ou relie.
  - Un lien est porte par le port de SORTIE de la source :
      {"portIn": <port cible>, "portOut": <port source>,
       "objIn": <id op cible>, "objOut": <id op source>}
  - Un port relie ne serialise pas sa valeur, et un port d'ENTREE relie
    disparait purement et simplement de `portsIn`.

Usage :
    python cables/build_cables_patch.py --template chemin/vers/un_patch.cables
"""

from __future__ import annotations

import argparse
import json
import random
import string
import time
from pathlib import Path

# UUID des types d'ops, releves dans le depot cables-gl/cables.
SIDEBAR = "5a681c35-78ce-4cb3-9858-bc79c34c6819"        # Ops.Sidebar.Sidebar
WEBSOCKET = "e747dc72-8214-41ca-9aae-9041f20dd6ac"      # Ops.Net.WebSocket.WebSocket_v2
GET_NUMBER = "a7335e79-046e-40da-9e9c-db779b0a5e53"     # Ops.Json.ObjectGetNumber_v2
GET_STRING = "c04a204d-cd52-401f-80c9-02da396ed676"     # Ops.Json.ObjectGetString_v2
DISPLAY = "3dd9927e-0d34-4442-8a8a-0ab843aee6e3"        # Ops.Sidebar.DisplayValue_v2
MULTIPLY = "1bbdae06-fbb2-489b-9bcc-36c9d65bd441"       # Ops.Math.Multiply
NUM_TO_STR = "5c6d375a-82db-4366-8013-93f56b4061a9"     # Ops.String.NumberToString_v2

# Noms de ports, tels que declares par chaque op (attention aux majuscules :
# ObjectGetNumber_v2 expose "Data", ObjectGetString_v2 expose "data").
PORT_DATA_NUMBER = "Data"
PORT_DATA_STRING = "data"


class Patch:
    """Assemble des operateurs et leurs liens, puis rend un fichier .cables."""

    def __init__(self, nom: str):
        self.nom = nom
        self.ops: list[dict] = []
        self._par_id: dict[str, dict] = {}

    @staticmethod
    def _identifiant() -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(random.choice(alphabet) for _ in range(9))

    def ajoute(self, op_id: str, x: float, y: float, **entrees) -> str:
        identifiant = self._identifiant()
        op = {
            "opId": op_id,
            "id": identifiant,
            "attribs": {},
            "uiAttribs": {"translate": {"x": x, "y": y}},
        }
        if entrees:
            op["portsIn"] = [{"name": nom, "value": valeur}
                             for nom, valeur in entrees.items()]
        self.ops.append(op)
        self._par_id[identifiant] = op
        return identifiant

    def relie(self, source: str, port_source: str, cible: str, port_cible: str) -> None:
        op = self._par_id[source]
        sorties = op.setdefault("portsOut", [])
        port = next((p for p in sorties if p["name"] == port_source), None)
        if port is None:
            port = {"name": port_source, "links": []}
            sorties.append(port)
        port.setdefault("links", []).append({
            "portIn": port_cible,
            "portOut": port_source,
            "objIn": cible,
            "objOut": source,
        })
        # Un port d'entree relie ne figure plus dans portsIn.
        cible_op = self._par_id[cible]
        if "portsIn" in cible_op:
            cible_op["portsIn"] = [p for p in cible_op["portsIn"]
                                   if p["name"] != port_cible]
            if not cible_op["portsIn"]:
                del cible_op["portsIn"]

    def rendu(self, gabarit: dict | None = None) -> dict:
        maintenant = int(time.time() * 1000)
        patch = {
            "_id": "".join(random.choice("0123456789abcdef") for _ in range(24)),
            "shortId": "".join(random.choice(string.ascii_letters + string.digits)
                               for _ in range(6)),
            "name": self.nom,
            "description": "",
            "userId": "",
            "cachedUsername": "",
            "created": maintenant,
            "updated": maintenant,
            "visibility": "private",
            "ops": self.ops,
            "settings": {"licence": "none"},
            "userList": [],
            "teams": [],
            "log": [],
            "ui": {
                "viewBox": {},
                "renderer": {"w": 640, "h": 320, "s": 1},
                "timeline": {},
                "texPreview": {},
                "bookmarks": [],
            },
            "summary": {"title": self.nom},
        }
        if gabarit:
            # Reprend l'identite locale d'un patch existant (utilisateur,
            # version du logiciel) pour coller a l'installation cible.
            for cle in ("userId", "cachedUsername", "userList", "buildInfo"):
                if cle in gabarit:
                    patch[cle] = gabarit[cle]
        return patch


def construit(url: str, gabarit: dict | None = None) -> dict:
    """Barre laterale affichant vehicule, vitesse et regime moteur."""
    patch = Patch("Forza telemetry")

    sidebar = patch.ajoute(SIDEBAR, -600, 0, **{"Title": "Forza"})
    # `?full=1` dans l'URL : la passerelle emet en differentiel, or cables
    # traite chaque message isolement, sans etat accumule. Un champ fige
    # (car_name) serait alors absent de presque toutes les trames et son
    # afficheur clignoterait au rythme des resynchronisations.
    # Le reglage passe par l'URL et non par une commande, car l'op WebSocket
    # publie `Connected` AVANT `Connection` : un envoi declenche par
    # `Connected` partirait sans connexion etablie.
    websocket = patch.ajoute(WEBSOCKET, -1100, 0, URL=url)

    def ajoute_ligne(indice, libelle, cle, numerique, facteur=None, decimales=0):
        y = 180 + indice * 200
        if numerique:
            extrait = patch.ajoute(GET_NUMBER, -1100, y, Key=cle)
            patch.relie(websocket, "Result", extrait, PORT_DATA_NUMBER)
            source, port = extrait, "Result"
            if facteur is not None:
                produit = patch.ajoute(MULTIPLY, -1100, y + 60, number2=facteur)
                patch.relie(source, port, produit, "number1")
                source, port = produit, "result"
            texte = patch.ajoute(NUM_TO_STR, -1100, y + 120,
                                 **{"Decimal Places": decimales})
            patch.relie(source, port, texte, "Number")
            source, port = texte, "Result"
        else:
            extrait = patch.ajoute(GET_STRING, -1100, y, Key=cle)
            patch.relie(websocket, "Result", extrait, PORT_DATA_STRING)
            source, port = extrait, "Result"

        afficheur = patch.ajoute(DISPLAY, -600, y, **{"Text": libelle})
        patch.relie(sidebar, "childs", afficheur, "link")
        patch.relie(source, port, afficheur, "Value")

    ajoute_ligne(0, "Vehicle", "car_name", numerique=False)
    ajoute_ligne(1, "Speed (km/h)", "speed", numerique=True, facteur=3.6)
    ajoute_ligne(2, "Engine rpm", "current_engine_rpm", numerique=True)

    return patch.rendu(gabarit)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a cables.gl patch wired to the Forza bridge")
    parser.add_argument("--url", default="ws://localhost:8765/?full=1",
                        help="WebSocket address of the bridge")
    parser.add_argument("--output", default=None, help=".cables file to write")
    parser.add_argument("--template", default=None,
                        help="Existing .cables patch whose local identity to reuse")
    args = parser.parse_args()

    gabarit = None
    if args.template:
        gabarit = json.loads(Path(args.template).read_text(encoding="utf-8"))

    destination = Path(args.output) if args.output else \
        Path(__file__).with_name("forza_telemetry.cables")
    destination.write_text(
        json.dumps(construit(args.url, gabarit), indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"Patch written: {destination}")


if __name__ == "__main__":
    main()
