"""Met a jour la table ordinal -> nom de vehicule.

La table livree vient d'une liste communautaire, forcement figee : les
voitures ajoutees par les mises a jour du jeu s'affichent en
"Vehicule inconnu (ordinal N)". Ce script recharge la liste et rend compte
des differences, au lieu de laisser la table vieillir en silence.

Source : gist communautaire "Forza Horizon 6 Car Ordinals" (HDR). Ce n'est
PAS une source officielle : la mise a jour FUSIONNE, elle ne remplace pas.
Les entrees locales absentes de la source sont conservees sauf --supprimer.

Usage :
    python tools/update_car_table.py            # apercu, n'ecrit rien
    python tools/update_car_table.py --ecrire   # applique la fusion
    python tools/update_car_table.py --fichier liste.json --ecrire
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

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
    parser.add_argument("--url", default=GIST_DEFAUT,
                        help="Autre source que le gist par defaut")
    parser.add_argument("--supprimer", action="store_true",
                        help="Retire aussi les entrees absentes de la source. "
                             "Sans cette option les entrees locales sont "
                             "conservees (la source n'est pas officielle).")
    args = parser.parse_args()

    try:
        source = (json.loads(Path(args.fichier).read_text(encoding="utf-8"))
                  if args.fichier else telecharge(args.url))
        # en_table et la lecture de la table sont DANS le try : une source mal
        # formee produisait sinon une trace au lieu du message prevu.
        nouvelle = en_table(source)
        ancienne = (json.loads(TABLE.read_text(encoding="utf-8"))
                    if TABLE.exists() else {})
    except Exception as exc:  # noqa: BLE001 - reseau, fichier ou format
        print(f"Recuperation impossible : {exc}", file=sys.stderr)
        return 1

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
        restants, resolus = [], []
        for o in inconnus:
            (resolus if str(o) in nouvelle else restants).append(o)
        if resolus:
            print(f"\n{len(resolus)} ordinal(aux) rencontres en jeu sont "
                  f"desormais connus : {resolus}")
        if restants:
            print(f"{len(restants)} ordinal(aux) rencontres en jeu restent "
                  f"absents de la liste : {restants}")

    # FUSION et non remplacement : la source n'est pas officielle, et un
    # remplacement en bloc annulait les corrections faites a la main.
    resultat = dict(ancienne)
    resultat.update(nouvelle)
    if args.supprimer:
        for ordinal in retraits:
            resultat.pop(ordinal, None)
    elif retraits:
        print(f"\n{len(retraits)} entree(s) locale(s) absente(s) de la source "
              f"sont CONSERVEES (--supprimer pour les retirer).")
    resultat = dict(sorted(resultat.items(), key=lambda kv: int(kv[0])))

    if not args.ecrire:
        print("\nApercu seulement. Relancer avec --ecrire pour appliquer.")
        return 0
    if resultat == ancienne:
        print("\nRien a changer.")
        return 0

    # Ecriture atomique : `write_text` tronque avant d'ecrire, et un JSON
    # tronque fait renvoyer {} a car_lookup, qui le met en cache pour tout le
    # processus — chaque voiture devient alors "inconnue".
    temporaire = TABLE.with_suffix(TABLE.suffix + ".tmp")
    temporaire.write_text(json.dumps(resultat, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporaire, TABLE)
    print(f"\n{TABLE.name} mis a jour : {len(resultat)} vehicules "
          f"({len(ajouts)} ajout(s), {len(renommes)} renommage(s)"
          + (f", {len(retraits)} retrait(s)" if args.supprimer else "") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
