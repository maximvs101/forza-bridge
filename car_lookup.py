"""Correspondance car_ordinal -> nom du vehicule.

Forza n'envoie qu'un identifiant numerique (`car_ordinal`) dans sa telemetrie.
Ce module traduit cet identifiant en nom lisible ("2003 Porsche Carrera GT").

Source des donnees : liste communautaire d'ordinaux Forza Horizon 6
(gist HDR), convertie en ordinal -> nom dans car_ordinals.json, puis
completee a la main. Le nombre exact est donne par `known_count()` — le
citer ici le condamnerait a devenir faux au premier ajout.

Cette liste est communautaire et donc potentiellement incomplete : les
vehicules ajoutes par les mises a jour du jeu apres cette date renverront
None. Le code appelant doit toujours gerer ce cas (voir `describe`).

Egalement disponibles ici : les libelles des enumerations `car_class` et
`drivetrain_type`, definies dans la documentation du format Data Out.
"""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from pathlib import Path

# Publics : `tools/update_car_table.py` ecrit ce que ce module lit, les deux
# doivent designer le meme fichier.
DATA_PATH = Path(__file__).with_name("car_ordinals.json")
_DATA_PATH = DATA_PATH
# Ordinaux rencontres mais absents de la table : conserves pour pouvoir
# completer la liste plus tard, au lieu de decouvrir le manque par hasard.
UNKNOWN_PATH = Path(__file__).with_name("car_ordinals_unknown.json")
_UNKNOWN_PATH = UNKNOWN_PATH

_inconnus: set[int] = set()
_inconnus_charges = False
_verrou = threading.Lock()

# EDrivetrainType, tel que documente dans le format Data Out de Forza.
DRIVETRAIN_LABELS = {0: "FWD", 1: "RWD", 2: "AWD"}

# car_class : 0 (classe D) a 7 (classe X).
# L'index 4 = S1 est VERIFIE en jeu (FH6, 28/07/2026) : une Audi R8 GT affichee
# "S1 769" par le jeu remonte car_class=4 et PI=769.
# ATTENTION : ne pas deduire la classe a partir du PI. Les bandes classiques
# FH4/FH5 (S1 = 801-900) ne s'appliquent pas a FH6, ou un PI de 769 est deja S1.
# Les index 6 et 7 restent supposes (la doc annonce 8 valeurs pour 7 classes).
CAR_CLASS_LABELS = {
    0: "D", 1: "C", 2: "B", 3: "A",
    4: "S1", 5: "S2", 6: "X", 7: "X",
}


@lru_cache(maxsize=1)
def _table() -> dict[int, str]:
    """Charge la table ordinal -> nom (une seule fois, mise en cache)."""
    try:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {int(ordinal): name for ordinal, name in raw.items()}


def car_name(ordinal: int | float | None) -> str | None:
    """Nom du vehicule pour cet ordinal, ou None s'il est inconnu."""
    if ordinal is None:
        return None
    try:
        return _table().get(int(ordinal))
    except (TypeError, ValueError):
        return None


def describe(ordinal: int | float | None) -> str:
    """Nom du vehicule, ou un libelle de repli explicite si l'ordinal est inconnu.

    Un ordinal inconnu est enregistre : la table vient d'une liste
    communautaire figee, les voitures ajoutees par les mises a jour du jeu y
    manquent forcement.
    """
    name = car_name(ordinal)
    if name:
        return name
    if ordinal in (None, 0):
        return "-"
    note_unknown(ordinal)
    return f"Unknown vehicle (ordinal {int(ordinal)})"


def _charge_inconnus() -> None:
    """Reprend le journal existant. A appeler en tenant `_verrou`.

    Sans cette relecture le fichier etait en ecriture seule : le premier
    ordinal inconnu d'une nouvelle session ecrasait tout l'historique, ce qui
    annulait la raison d'etre du journal.
    """
    global _inconnus_charges
    if _inconnus_charges:
        return
    _inconnus_charges = True
    try:
        anciens = json.loads(_UNKNOWN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(anciens, list):
        for valeur in anciens:
            try:
                _inconnus.add(int(valeur))
            except (TypeError, ValueError):
                continue


def _ecrit_inconnus() -> None:
    """Ecrit le journal. A appeler en tenant `_verrou`.

    Passage par un fichier temporaire puis `os.replace` : `write_text`
    tronque avant d'ecrire, si bien qu'une lecture concurrente pouvait
    tomber sur un JSON vide, silencieusement interprete comme "aucun
    inconnu".
    """
    temporaire = _UNKNOWN_PATH.with_suffix(_UNKNOWN_PATH.suffix + ".tmp")
    try:
        temporaire.write_text(json.dumps(sorted(_inconnus), indent=1),
                              encoding="utf-8")
        os.replace(temporaire, _UNKNOWN_PATH)
    except OSError:
        try:
            temporaire.unlink(missing_ok=True)
        except OSError:
            pass


def note_unknown(ordinal: int | float) -> None:
    """Retient un ordinal absent de la table, et l'ecrit sur disque.

    L'ecriture a lieu SOUS le verrou : la relacher avant d'ecrire laissait
    deux appels concurrents inverser l'ordre de leurs ecritures, et
    l'instantane le plus ancien gagnait — un ordinal disparaissait du fichier
    sans que la garde en memoire permette une nouvelle tentative.
    """
    try:
        valeur = int(ordinal)
    except (TypeError, ValueError):
        return
    with _verrou:
        _charge_inconnus()
        if valeur in _inconnus:
            return
        _inconnus.add(valeur)
        _ecrit_inconnus()


def unknown_seen() -> list[int]:
    """Ordinaux inconnus connus, journal existant compris."""
    with _verrou:
        _charge_inconnus()
        return sorted(_inconnus)


def drivetrain_label(value: int | float | None) -> str:
    try:
        return DRIVETRAIN_LABELS.get(int(value), "-")
    except (TypeError, ValueError):
        return "-"


def car_class_label(value: int | float | None) -> str:
    try:
        return CAR_CLASS_LABELS.get(int(value), "-")
    except (TypeError, ValueError):
        return "-"


def known_count() -> int:
    """Nombre de vehicules presents dans la table."""
    return len(_table())
