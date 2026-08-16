"""Correspondance car_ordinal -> nom du vehicule.

Forza n'envoie qu'un identifiant numerique (`car_ordinal`) dans sa telemetrie.
Ce module traduit cet identifiant en nom lisible ("2003 Porsche Carrera GT").

Source des donnees : liste communautaire d'ordinaux Forza Horizon 6
(gist HDR, etat au 14/07/2026), convertie en ordinal -> nom dans
car_ordinals.json. 651 vehicules, sans doublon d'ordinal.

Cette liste est communautaire et donc potentiellement incomplete : les
vehicules ajoutes par les mises a jour du jeu apres cette date renverront
None. Le code appelant doit toujours gerer ce cas (voir `describe`).

Egalement disponibles ici : les libelles des enumerations `car_class` et
`drivetrain_type`, definies dans la documentation du format Data Out.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).with_name("car_ordinals.json")

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
    """Nom du vehicule, ou un libelle de repli explicite si l'ordinal est inconnu."""
    name = car_name(ordinal)
    if name:
        return name
    if ordinal in (None, 0):
        return "-"
    return f"Vehicule inconnu (ordinal {int(ordinal)})"


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
