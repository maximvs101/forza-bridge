"""Met a jour la table ordinal -> nom de vehicule.

La table livree vient d'une liste communautaire, forcement figee : les
voitures ajoutees par les mises a jour du jeu s'affichent en
"Vehicule inconnu (ordinal N)". Ce script recharge la liste et rend compte
des differences, au lieu de laisser la table vieillir en silence.

Source : gist communautaire "Forza Horizon 6 Car Ordinals" (HDR). Ce n'est
PAS une source officielle : la mise a jour FUSIONNE, elle ne remplace pas.
Les entrees locales absentes de la source sont conservees sauf --remove.

Usage :
    python tools/update_car_table.py           # apercu, n'ecrit rien
    python tools/update_car_table.py --write   # applique la fusion
    python tools/update_car_table.py --file liste.json --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

# Cette ligne est AFFICHEE par --help : elle est donc en anglais, contrairement
# au docstring ci-dessus qui n'est que de la documentation interne.
# NE PAS la remonter avant `from __future__` : c'est une erreur de syntaxe, et
# `ast.parse` ne la signale pas — le test de langue lisait donc le fichier sans
# broncher alors que l'outil ne demarrait plus.
DESCRIPTION = "Update the ordinal -> vehicle name table."

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

import car_lookup  # noqa: E402 - apres l'ajustement de sys.path

# Chemins pris chez car_lookup : les redefinir ici laissait l'outil ecrire
# ailleurs que la ou le programme lit, sans que rien ne le signale.
TABLE = car_lookup.DATA_PATH
INCONNUS = car_lookup.UNKNOWN_PATH

GIST_DEFAUT = "https://api.github.com/gists/0659d1717bc61504bf83750628963f4f"
ENTETES = {"User-Agent": "forza-bridge"}


def _json_distant(url: str):
    """Une seule politique HTTP : en-tetes, delai, decodage."""
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse)


def telecharge(url: str = GIST_DEFAUT) -> dict[str, str]:
    """Recupere la liste communautaire, au format nom -> ordinal."""
    gist = _json_distant(url)
    for fichier in gist.get("files", {}).values():
        if not fichier.get("filename", "").lower().endswith(".json"):
            continue
        if fichier.get("truncated") or "content" not in fichier:
            return _json_distant(fichier["raw_url"])
        return json.loads(fichier["content"])
    raise RuntimeError("no JSON file in the gist")


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
        print(f"WARNING: {len(collisions)} duplicate ordinal(s), "
              f"first occurrence kept")
        for cle, garde, ecarte in collisions[:5]:
            print(f"  {cle}: kept \"{garde}\", dropped \"{ecarte}\"")
    return dict(sorted(table.items(), key=lambda kv: int(kv[0])))


def compare(ancienne: dict, nouvelle: dict) -> tuple[list, list, list]:
    ajouts = [o for o in nouvelle if o not in ancienne]
    retraits = [o for o in ancienne if o not in nouvelle]
    renommes = [(o, ancienne[o], nouvelle[o]) for o in nouvelle
                if o in ancienne and ancienne[o] != nouvelle[o]]
    return ajouts, retraits, renommes


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--write", action="store_true",
                        help="Apply the update (otherwise it is only a preview)")
    parser.add_argument("--file", default=None,
                        help="Use a local file instead of downloading")
    parser.add_argument("--url", default=GIST_DEFAUT,
                        help="Source other than the default gist")
    parser.add_argument("--remove", action="store_true",
                        help="Also remove entries missing from the source. "
                             "Without this, local entries are "
                             "kept (the source is not official).")
    args = parser.parse_args()

    try:
        source = (json.loads(Path(args.file).read_text(encoding="utf-8"))
                  if args.file else telecharge(args.url))
        # en_table et la lecture de la table sont DANS le try : une source mal
        # formee produisait sinon une trace au lieu du message prevu.
        nouvelle = en_table(source)
        ancienne = (json.loads(TABLE.read_text(encoding="utf-8"))
                    if TABLE.exists() else {})
    except Exception as exc:  # noqa: BLE001 - reseau, fichier ou format
        print(f"Could not fetch: {exc}", file=sys.stderr)
        return 1

    ajouts, retraits, renommes = compare(ancienne, nouvelle)
    print(f"current table: {len(ancienne)} vehicles")
    print(f"fetched list:  {len(nouvelle)} vehicles")
    print(f"  + {len(ajouts)} added   - {len(retraits)} removed   "
          f"~ {len(renommes)} renamed")
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
        restants, resolus = [], []
        for o in inconnus:
            (resolus if str(o) in nouvelle else restants).append(o)
        if resolus:
            print(f"\n{len(resolus)} ordinal(s) seen in game are now "
                  f"known: {resolus}")
        if restants:
            print(f"{len(restants)} ordinal(s) seen in game are still "
                  f"missing from the list: {restants}")

    # FUSION et non remplacement : la source n'est pas officielle, et un
    # remplacement en bloc annulait les corrections faites a la main.
    resultat = dict(ancienne)
    resultat.update(nouvelle)
    if args.remove:
        for ordinal in retraits:
            resultat.pop(ordinal, None)
    elif retraits:
        print(f"\n{len(retraits)} local entr(y/ies) missing from the source "
              f"are KEPT (--remove to drop them).")
    resultat = dict(sorted(resultat.items(), key=lambda kv: int(kv[0])))

    if not args.write:
        print("\nPreview only. Re-run with --write to apply.")
        return 0
    if resultat == ancienne:
        print("\nNothing to change.")
        return 0

    # Ecriture atomique : `write_text` tronque avant d'ecrire, et un JSON
    # tronque fait renvoyer {} a car_lookup, qui le met en cache pour tout le
    # processus — chaque voiture devient alors "inconnue".
    temporaire = TABLE.with_suffix(TABLE.suffix + ".tmp")
    temporaire.write_text(json.dumps(resultat, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporaire, TABLE)
    print(f"\n{TABLE.name} updated: {len(resultat)} vehicles "
          f"({len(ajouts)} added, {len(renommes)} renamed"
          + (f", {len(retraits)} removed" if args.remove else "") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
