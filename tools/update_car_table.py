"""Met a jour la table ordinal -> nom de vehicule.

La table livree vient d'une liste communautaire, forcement figee : les
voitures ajoutees par les mises a jour du jeu s'affichent en
"Vehicule inconnu (ordinal N)". Ce script recharge la liste et rend compte
des differences, au lieu de laisser la table vieillir en silence.

Source : gist communautaire "Forza Horizon 6 Car Ordinals" (HDR). Ce n'est
PAS une source officielle — d'ou le compte-rendu detaille plutot qu'un
remplacement muet.

Usage :
    python tools/update_car_table.py            # apercu, n'ecrit rien
    python tools/update_car_table.py --ecrire   # applique la mise a jour
    python tools/update_car_table.py --fichier liste.json --ecrire
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TABLE = RACINE / "car_ordinals.json"
INCONNUS = RACINE / "car_ordinals_unknown.json"

GIST = ("https://api.github.com/gists/0659d1717bc61504bf83750628963f4f")


def telecharge() -> dict[str, str]:
    """Recupere la liste communautaire, au format nom -> ordinal."""
    requete = urllib.request.Request(GIST, headers={"User-Agent": "forza-bridge"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        gist = json.load(reponse)
    for fichier in gist.get("files", {}).values():
        if fichier.get("filename", "").lower().endswith(".json"):
            if fichier.get("truncated"):
                with urllib.request.urlopen(
                        urllib.request.Request(fichier["raw_url"],
                                               headers={"User-Agent": "forza-bridge"}),
                        timeout=30) as brut:
                    return json.load(brut)
            return json.loads(fichier["content"])
    raise RuntimeError("aucun fichier JSON dans le gist")


def en_table(nom_vers_ordinal: dict) -> dict[str, str]:
    """Inverse nom -> ordinal en ordinal -> nom, en signalant les collisions."""
    table: dict[str, str] = {}
    collisions = []
    for nom, ordinal in nom_vers_ordinal.items():
        cle = str(ordinal)
        if cle in table:
            collisions.append((cle, table[cle], nom))
            continue
        table[cle] = nom
    if collisions:
        print(f"ATTENTION : {len(collisions)} ordinal(aux) en double, "
              f"premiere occurrence conservee")
        for cle, garde, ecarte in collisions[:5]:
            print(f"  {cle} : garde \"{garde}\", ecarte \"{ecarte}\"")
    return dict(sorted(table.items(), key=lambda kv: int(kv[0])))


def compare(ancienne: dict, nouvelle: dict) -> tuple[list, list, list]:
    ajouts = [o for o in nouvelle if o not in ancienne]
    retraits = [o for o in ancienne if o not in nouvelle]
    renommes = [(o, ancienne[o], nouvelle[o]) for o in nouvelle
                if o in ancienne and ancienne[o] != nouvelle[o]]
    return ajouts, retraits, renommes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ecrire", action="store_true",
                        help="Applique la mise a jour (sans cela, simple apercu)")
    parser.add_argument("--fichier", default=None,
                        help="Utilise un fichier local au lieu de telecharger")
    args = parser.parse_args()

    try:
        source = (json.loads(Path(args.fichier).read_text(encoding="utf-8"))
                  if args.fichier else telecharge())
    except Exception as exc:  # noqa: BLE001 - reseau ou fichier
        print(f"Recuperation impossible : {exc}", file=sys.stderr)
        return 1

    nouvelle = en_table(source)
    ancienne = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else {}

    ajouts, retraits, renommes = compare(ancienne, nouvelle)
    print(f"table actuelle : {len(ancienne)} vehicules")
    print(f"liste recuperee : {len(nouvelle)} vehicules")
    print(f"  + {len(ajouts)} ajout(s)   - {len(retraits)} retrait(s)   "
          f"~ {len(renommes)} renommage(s)")
    for ordinal in ajouts[:10]:
        print(f"  + {ordinal} {nouvelle[ordinal]}")
    for ordinal in retraits[:10]:
        print(f"  - {ordinal} {ancienne[ordinal]}")
    for ordinal, avant, apres in renommes[:10]:
        print(f"  ~ {ordinal} \"{avant}\" -> \"{apres}\"")

    # Les ordinaux rencontres en jeu et toujours absents meritent d'etre
    # signales : c'est la seule trace de ce qui manque reellement.
    if INCONNUS.exists():
        try:
            inconnus = json.loads(INCONNUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            inconnus = []
        restants = [o for o in inconnus if str(o) not in nouvelle]
        resolus = [o for o in inconnus if str(o) in nouvelle]
        if resolus:
            print(f"\n{len(resolus)} ordinal(aux) rencontres en jeu sont "
                  f"desormais connus : {resolus}")
        if restants:
            print(f"{len(restants)} ordinal(aux) rencontres en jeu restent "
                  f"absents de la liste : {restants}")

    if not args.ecrire:
        print("\nApercu seulement. Relancer avec --ecrire pour appliquer.")
        return 0
    if not ajouts and not retraits and not renommes:
        print("\nRien a changer.")
        return 0

    TABLE.write_text(json.dumps(nouvelle, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"\n{TABLE.name} mis a jour : {len(nouvelle)} vehicules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
