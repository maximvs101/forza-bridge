"""Ou lire, et ou ecrire, selon la facon dont le programme est lance.

Lance depuis les sources, tout vit dans le dossier du projet et c'est bien
ainsi. Lance depuis un executable PyInstaller, le programme est extrait dans
un dossier TEMPORAIRE efface a la sortie : y ecrire `config.json` revient a
perdre les reglages a chaque fermeture, sans le moindre message. Le defaut
serait invisible jusqu'a ce qu'un utilisateur se demande pourquoi ses canaux
ne sont jamais memorises.

Deux natures de fichiers, donc deux emplacements :

  - `data_path()` : livre avec le programme, lu seulement (table des
    vehicules, overlay). Il suit l'executable, dossier temporaire compris.
  - `state_path()` : doit SURVIVRE a la fermeture (reglages, ordinaux
    rencontres). Depuis un executable, il va dans le dossier de
    l'utilisateur.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller pose `sys.frozen` et `sys._MEIPASS`.
FROZEN = bool(getattr(sys, "frozen", False))

# Dossier des sources : reference quand on tourne depuis le depot.
SOURCE_DIR = Path(__file__).resolve().parent

APP_NAME = "forza-bridge"


def data_path(nom: str) -> Path:
    """Fichier livre avec le programme, en lecture seule.

    `Path(__file__).with_name(...)` suffit dans les deux cas : PyInstaller
    extrait les donnees a cote des modules.
    """
    return SOURCE_DIR / nom


def state_dir() -> Path:
    """Dossier ou ecrire ce qui doit survivre a la fermeture."""
    if not FROZEN:
        # Depuis les sources : a cote du code, comme avant. Changer cela
        # deplacerait la configuration existante des utilisateurs du depot.
        return SOURCE_DIR

    base = os.environ.get("APPDATA") or os.environ.get("XDG_STATE_HOME")
    dossier = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME}"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Dossier utilisateur inaccessible : plutot que d'echouer, on se
        # rabat a cote de l'executable. Ecrire la peut echouer aussi (dossier
        # protege), mais les appelants traitent deja ce cas.
        return Path(sys.executable).resolve().parent
    return dossier


def state_path(nom: str) -> Path:
    return state_dir() / nom
