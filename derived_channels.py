"""Canaux derives, deja mis a l'echelle.

Le jeu emet des unites brutes : vitesse en m/s, pedales en octets 0-255,
angles en radians, temperatures en Fahrenheit. Chaque consommateur refaisait
donc les memes conversions : chaque consommateur avait sa propre
multiplication par 3,6.

Ces canaux sont calcules une fois dans le pont et diffuses comme les autres :
ils traversent l'OSC, le WebSocket, l'interface et le message d'accueil sans
traitement particulier. Les grandeurs bornees (0-1, -1..1) se branchent
directement sur une opacite, une echelle ou un volume.

Les canaux bruts restent emis : rien n'est remplace, tout est ajoute.
"""

from __future__ import annotations

import math

G = 9.80665  # acceleration de la pesanteur, m/s2
STEER_MAX = 127.0  # `steer` est un octet signe
PEDAL_MAX = 255.0  # accelerateur, frein, embrayage et frein a main

# Valeur que le jeu ecrit dans `gear` pendant un changement de rapport, mesuree
# le 17 aout 2026 sur deux voitures (dont une a 5 rapports, donc ce n'est pas
# un onzieme rapport) : 13 bouffees de 132 a 233 ms sur 45 s de capture brute,
# ou SEUL l'octet 319 change — ses voisins (accel, brake, clutch, hand_brake,
# steer, driving_line) restent immobiles, ce qui exclut un desalignement.
# Non documente par Turn 10 : ce n'est donc pas un nom officiel mais un
# constat. On teste l'egalite stricte plutot qu'un seuil : si une autre valeur
# apparaissait, `gear` la montrerait telle quelle au lieu d'etre silencieusement
# traduite en "changement de rapport".
SHIFTING_GEAR = 11


def _borne(valeur: float, mini: float, maxi: float) -> float:
    return max(mini, min(maxi, valeur))


def _fahrenheit_en_celsius(valeur: float) -> float:
    return (valeur - 32.0) * 5.0 / 9.0


# Canal derive -> (canal source, fonction). Les conversions simples passent
# par cette table ; les cas a plusieurs sources sont traites dans compute().
_SIMPLES: dict[str, tuple[str, object]] = {
    "speed_kmh": ("speed", lambda v: v * 3.6),
    "speed_mph": ("speed", lambda v: v * 2.236936),

    "throttle": ("accel", lambda v: _borne(v / PEDAL_MAX, 0.0, 1.0)),
    "brake_pedal": ("brake", lambda v: _borne(v / PEDAL_MAX, 0.0, 1.0)),
    "clutch_pedal": ("clutch", lambda v: _borne(v / PEDAL_MAX, 0.0, 1.0)),
    "handbrake_pedal": ("hand_brake", lambda v: _borne(v / PEDAL_MAX, 0.0, 1.0)),
    # L'octet signe descend a -128 : on borne pour garantir -1..1.
    "steer_norm": ("steer", lambda v: _borne(v / STEER_MAX, -1.0, 1.0)),

    "g_lateral": ("acceleration_x", lambda v: v / G),
    "g_vertical": ("acceleration_y", lambda v: v / G),
    "g_longitudinal": ("acceleration_z", lambda v: v / G),

    "yaw_deg": ("yaw", math.degrees),
    "pitch_deg": ("pitch", math.degrees),
    "roll_deg": ("roll", math.degrees),

    "tire_temp_fl_c": ("tire_temp_fl", _fahrenheit_en_celsius),
    "tire_temp_fr_c": ("tire_temp_fr", _fahrenheit_en_celsius),
    "tire_temp_rl_c": ("tire_temp_rl", _fahrenheit_en_celsius),
    "tire_temp_rr_c": ("tire_temp_rr", _fahrenheit_en_celsius),
}

_SLIP = ("tire_combined_slip_fl", "tire_combined_slip_fr",
         "tire_combined_slip_rl", "tire_combined_slip_rr")

# Ordre d'affichage dans l'interface et dans le message d'accueil.
DERIVED_CHANNELS: list[str] = [
    "speed_kmh", "speed_mph", "rpm_ratio",
    "throttle", "brake_pedal", "clutch_pedal", "handbrake_pedal", "steer_norm",
    "g_lateral", "g_vertical", "g_longitudinal",
    "yaw_deg", "pitch_deg", "roll_deg",
    "tire_temp_fl_c", "tire_temp_fr_c", "tire_temp_rl_c", "tire_temp_rr_c",
    "slip_max", "shifting",
]

DERIVED_UNITS: dict[str, str] = {
    "speed_kmh": "km/h",
    "speed_mph": "mph",
    "rpm_ratio": "0-1 (1 = redline)",
    "throttle": "0-1",
    "brake_pedal": "0-1",
    "clutch_pedal": "0-1",
    "handbrake_pedal": "0-1",
    "steer_norm": "-1..1 (left/right)",
    "g_lateral": "g",
    "g_vertical": "g",
    "g_longitudinal": "g",
    "yaw_deg": "degrees",
    "pitch_deg": "degrees",
    "roll_deg": "degrees",
    "tire_temp_fl_c": "degC",
    "tire_temp_fr_c": "degC",
    "tire_temp_rl_c": "degC",
    "tire_temp_rr_c": "degC",
    "slip_max": "normalised (|x| > 1 = grip loss)",
    "shifting": "0/1 (1 = no gear engaged)",
}


def compute(values: dict) -> dict:
    """Canaux derives pour une trame. Un champ source absent est ignore.

    Aucune exception n'est levee sur des donnees incompletes : un paquet
    "sled" ne porte pas la partie dash, et le jeu envoie des zeros en menu.
    """
    derives: dict[str, float] = {}

    for nom, (source, conversion) in _SIMPLES.items():
        brut = values.get(source)
        if isinstance(brut, (int, float)):
            derives[nom] = float(conversion(brut))

    # Regime rapporte a la zone rouge : depend de deux champs, et le
    # denominateur vaut 0 en menu.
    regime = values.get("current_engine_rpm")
    maximum = values.get("engine_max_rpm")
    if isinstance(regime, (int, float)) and isinstance(maximum, (int, float)):
        derives["rpm_ratio"] = _borne(regime / maximum, 0.0, 1.0) if maximum else 0.0

    # Glissement le plus fort des quatre roues : un seul canal suffit pour
    # declencher un effet, au lieu d'en surveiller quatre.
    glissements = [values[nom] for nom in _SLIP
                   if isinstance(values.get(nom), (int, float))]
    if glissements:
        derives["slip_max"] = float(max(abs(valeur) for valeur in glissements))

    # Changement de rapport en cours. `gear` garde sa valeur brute, 11
    # comprise : un consommateur qui mappe le rapport sur un nombre, une
    # couleur ou un son se sert de ce drapeau, sans qu'on ait a falsifier la
    # donnee d'origine.
    rapport = values.get("gear")
    if isinstance(rapport, int) and not isinstance(rapport, bool):
        derives["shifting"] = 1.0 if rapport == SHIFTING_GEAR else 0.0

    return derives
