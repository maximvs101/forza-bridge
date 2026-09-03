"""Lissage temporel, reglable canal par canal.

La telemetrie est bruitee — glissements de pneus, suspensions, vibrations de
surface tremblent en permanence. Lisser a la source profite a tous les
consommateurs d'un coup, au lieu que chacun refasse le sien.

Filtre exponentiel a CONSTANTE DE TEMPS, et non a coefficient fixe : la
cadence de la source varie (mesure sur FH6 : 60 Hz a l'arret, 30 Hz en
roulant, le jeu emettant un paquet par image rendue). Un coefficient fixe
lisserait donc deux fois plus fort en menu qu'en conduite. En repartant de
l'ecart de temps reel, le comportement ne depend plus de la cadence.

Le reglage `tau` est le temps de reponse en secondes : apres un echelon, la
sortie atteint 63 % de la nouvelle valeur au bout de tau. Plus tau est grand,
plus c'est lisse — et plus c'est en retard. Pour du visuel, 0,05 a 0,2 s
couvre l'essentiel des besoins.

LE LISSAGE NE REMPLACE JAMAIS UNE VALEUR. Un filtre deforme le signal par
construction : il retarde, et rabote les extremes (mesure sur un signal
propre : pics ramenes de 252 a 243 km/h). Ecraser le canal d'origine
falsifierait donc la telemetrie pour tous les consommateurs, y compris ceux
qui l'analysent ou l'enregistrent. Chaque canal lisse est publie A COTE du
brut, sous le nom `<canal>_smooth`. Meme principe que les canaux derives :
on ajoute, on ne remplace pas.
"""

from __future__ import annotations

import math

# Canaux qu'il ne faut JAMAIS lisser, quoi qu'on demande : une moyenne entre
# deux rapports de boite donnerait 2,7, et entre deux identifiants de vehicule
# un numero qui n'existe pas.
# Suffixe des canaux lisses. Le canal d'origine reste intact.
SUFFIX = "_smooth"

NOT_SMOOTHABLE = frozenset({
    "is_race_on", "timestamp_ms", "gear", "lap_number", "race_position",
    "car_ordinal", "car_class", "car_performance_index", "drivetrain_type",
    "num_cylinders", "car_category", "horizon_unknown_1", "horizon_unknown_2",
    "wheel_on_rumble_strip_fl", "wheel_on_rumble_strip_fr",
    "wheel_on_rumble_strip_rl", "wheel_on_rumble_strip_rr",
    "car_name",
    # Drapeau 0/1 : une moyenne donnerait 0,3 pendant un passage de rapport,
    # ce qui ne veut rien dire.
    "shifting",
})


def parse_settings(texte: str) -> dict[str, float]:
    """Lit une specification "canal=duree, canal=duree".

    Exemple : "speed_kmh=0.15, slip_max=0.05". Les entrees invalides ou
    portant sur un canal non lissable sont ignorees en silence : ce texte
    vient d'un champ de saisie ou d'une ligne de commande.
    """
    settings: dict[str, float] = {}
    for morceau in texte.replace(";", ",").split(","):
        morceau = morceau.strip()
        if not morceau or "=" not in morceau:
            continue
        nom, _, valeur = morceau.partition("=")
        nom = nom.strip()
        try:
            tau = float(valeur.strip())
        except ValueError:
            continue
        if nom and tau > 0 and nom not in NOT_SMOOTHABLE:
            settings[nom] = tau
    return settings


def format_settings(settings: dict[str, float]) -> str:
    return ", ".join(f"{nom}={tau:g}" for nom, tau in sorted(settings.items()))


class Smoother:
    """Applique un lissage par canal a des trames successives."""

    def __init__(self, settings: dict[str, float] | None = None):
        self._settings: dict[str, float] = {}
        self._state: dict[str, float] = {}
        self._last_time: float | None = None
        self.configure(settings or {})

    def configure(self, settings: dict[str, float]) -> None:
        """Remplace les settings. Les canaux retires repartent a zero."""
        self._settings = {nom: tau for nom, tau in settings.items()
                          if tau > 0 and nom not in NOT_SMOOTHABLE}
        self._state = {nom: valeur for nom, valeur in self._state.items()
                      if nom in self._settings}

    @property
    def settings(self) -> dict[str, float]:
        return dict(self._settings)

    @property
    def active(self) -> bool:
        return bool(self._settings)

    @property
    def produced_channels(self) -> list[str]:
        """Noms des canaux lisses publies, en plus des canaux d'origine."""
        return [nom + SUFFIX for nom in sorted(self._settings)]

    def reset(self) -> None:
        """Oublie l'etat courant.

        A appeler sur une discontinuite — changement de vehicule, reprise
        apres une interruption — pour que la sortie parte de la nouvelle
        valeur au lieu d'y glisser depuis l'ancienne.
        """
        self._state.clear()
        self._last_time = None

    def apply(self, values: dict, now: float) -> dict:
        """Renvoie la trame enrichie des canaux `<nom>_smooth`.

        Les valeurs d'origine ne sont jamais modifiees. `instant` est une
        horloge monotone.
        """
        if not self._settings:
            return values

        ecart = None
        if self._last_time is not None:
            ecart = now - self._last_time
        self._last_time = now

        sortie = dict(values)
        for nom, tau in self._settings.items():
            brut = values.get(nom)
            if not isinstance(brut, (int, float)) or isinstance(brut, bool):
                continue
            brut = float(brut)
            # Une valeur non finie n'est pas lissable et empoisonnerait
            # l'etat : on n'emet simplement pas le canal lisse cette fois-ci.
            if not math.isfinite(brut):
                continue

            precedent = self._state.get(nom)
            # Premiere valeur, ou ecart de temps inutilisable : on adopte la
            # valeur telle quelle plutot que de partir de zero, ce qui
            # produirait une rampe visible au demarrage.
            if precedent is None or ecart is None or ecart <= 0:
                self._state[nom] = brut
                sortie[nom + SUFFIX] = brut
                continue

            coefficient = 1.0 - math.exp(-ecart / tau)
            lisse = precedent + coefficient * (brut - precedent)
            self._state[nom] = lisse
            sortie[nom + SUFFIX] = lisse

        return sortie
