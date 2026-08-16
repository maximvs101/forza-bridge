"""Catalogue des canaux de telemetrie exposes dans l'interface.

Regroupe les champs de forza_telemetry.py par categorie pour l'affichage,
et definit une selection par defaut ("essentiels") pour un demarrage rapide.
Les champs internes non documentes (horizon_unknown_*) sont exclus.
"""

CATEGORIES: dict[str, list[str]] = {
    "General": ["is_race_on", "timestamp_ms"],
    "Moteur": ["engine_max_rpm", "engine_idle_rpm", "current_engine_rpm"],
    "Mouvement": [
        "acceleration_x", "acceleration_y", "acceleration_z",
        "velocity_x", "velocity_y", "velocity_z",
        "angular_velocity_x", "angular_velocity_y", "angular_velocity_z",
        "yaw", "pitch", "roll",
    ],
    "Position / course": [
        "position_x", "position_y", "position_z",
        "speed", "power", "torque",
        "distance_traveled", "best_lap_time", "last_lap_time",
        "current_lap_time", "current_race_time", "lap_number", "race_position",
    ],
    "Commandes": [
        "accel", "brake", "clutch", "hand_brake", "gear",
        "steer", "norm_driving_line", "norm_ai_brake_difference", "boost", "fuel",
    ],
    "Suspension": [
        "norm_suspension_travel_fl", "norm_suspension_travel_fr",
        "norm_suspension_travel_rl", "norm_suspension_travel_rr",
        "suspension_travel_meters_fl", "suspension_travel_meters_fr",
        "suspension_travel_meters_rl", "suspension_travel_meters_rr",
    ],
    "Pneus": [
        "tire_slip_ratio_fl", "tire_slip_ratio_fr", "tire_slip_ratio_rl", "tire_slip_ratio_rr",
        "tire_slip_angle_fl", "tire_slip_angle_fr", "tire_slip_angle_rl", "tire_slip_angle_rr",
        "tire_combined_slip_fl", "tire_combined_slip_fr", "tire_combined_slip_rl", "tire_combined_slip_rr",
        "tire_temp_fl", "tire_temp_fr", "tire_temp_rl", "tire_temp_rr",
        "wheel_rotation_speed_fl", "wheel_rotation_speed_fr",
        "wheel_rotation_speed_rl", "wheel_rotation_speed_rr",
        "wheel_on_rumble_strip_fl", "wheel_on_rumble_strip_fr",
        "wheel_on_rumble_strip_rl", "wheel_on_rumble_strip_rr",
        "wheel_in_puddle_fl", "wheel_in_puddle_fr", "wheel_in_puddle_rl", "wheel_in_puddle_rr",
        "surface_rumble_fl", "surface_rumble_fr", "surface_rumble_rl", "surface_rumble_rr",
    ],
    "Vehicule": [
        "car_ordinal", "car_class", "car_performance_index",
        "drivetrain_type", "num_cylinders", "car_category",
    ],
    # Champs presents dans le paquet Horizon mais jamais identifies par la
    # communaute. Ils etaient auparavant absents du catalogue tout en etant
    # emis par main.py : deux canaux arrivaient dans TouchDesigner sans
    # figurer nulle part. Listes ici, et decoches par defaut.
    "Non documente": [
        "horizon_unknown_1", "horizon_unknown_2",
    ],
}

ALL_CHANNELS: list[str] = [name for names in CATEGORIES.values() for name in names]

CATEGORY_OF: dict[str, str] = {
    name: category for category, names in CATEGORIES.items() for name in names
}

# Unites reelles des champs, telles qu'emises par le jeu. Publiees dans le
# message d'accueil WebSocket pour que chaque consommateur n'ait pas a
# redecouvrir les conversions (vitesse en m/s, pedales en octet 0-255...).
UNITS: dict[str, str] = {
    "speed": "m/s",
    "power": "W",
    "torque": "N.m",
    "current_engine_rpm": "tr/min",
    "engine_max_rpm": "tr/min",
    "engine_idle_rpm": "tr/min",
    "acceleration_x": "m/s2", "acceleration_y": "m/s2", "acceleration_z": "m/s2",
    "velocity_x": "m/s", "velocity_y": "m/s", "velocity_z": "m/s",
    "angular_velocity_x": "rad/s", "angular_velocity_y": "rad/s", "angular_velocity_z": "rad/s",
    "yaw": "rad", "pitch": "rad", "roll": "rad",
    "position_x": "m", "position_y": "m", "position_z": "m",
    "distance_traveled": "m",
    "best_lap_time": "s", "last_lap_time": "s",
    "current_lap_time": "s", "current_race_time": "s",
    "tire_temp_fl": "degF", "tire_temp_fr": "degF",
    "tire_temp_rl": "degF", "tire_temp_rr": "degF",
    "suspension_travel_meters_fl": "m", "suspension_travel_meters_fr": "m",
    "suspension_travel_meters_rl": "m", "suspension_travel_meters_rr": "m",
    "wheel_rotation_speed_fl": "rad/s", "wheel_rotation_speed_fr": "rad/s",
    "wheel_rotation_speed_rl": "rad/s", "wheel_rotation_speed_rr": "rad/s",
    "accel": "0-255", "brake": "0-255", "clutch": "0-255", "hand_brake": "0-255",
    "steer": "-127..127",
    "norm_driving_line": "-127..127", "norm_ai_brake_difference": "-127..127",
    "gear": "rapport (0 = marche arriere)",
    "timestamp_ms": "ms",
    "is_race_on": "0/1",

    # Grandeurs sans dimension : le declarer explicitement evite qu'un
    # consommateur confonde "sans unite" et "unite oubliee".
    "boost": "sans dimension",
    "fuel": "fraction 0-1",
    "lap_number": "numero de tour",
    "race_position": "place",
    "norm_suspension_travel_fl": "0-1 (0 = detente max, 1 = compression max)",
    "norm_suspension_travel_fr": "0-1 (0 = detente max, 1 = compression max)",
    "norm_suspension_travel_rl": "0-1 (0 = detente max, 1 = compression max)",
    "norm_suspension_travel_rr": "0-1 (0 = detente max, 1 = compression max)",
    "tire_slip_ratio_fl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_ratio_fr": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_ratio_rl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_ratio_rr": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_angle_fl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_angle_fr": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_angle_rl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_slip_angle_rr": "normalise (|x| > 1 = perte d'adherence)",
    "tire_combined_slip_fl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_combined_slip_fr": "normalise (|x| > 1 = perte d'adherence)",
    "tire_combined_slip_rl": "normalise (|x| > 1 = perte d'adherence)",
    "tire_combined_slip_rr": "normalise (|x| > 1 = perte d'adherence)",
    "wheel_on_rumble_strip_fl": "0/1",
    "wheel_on_rumble_strip_fr": "0/1",
    "wheel_on_rumble_strip_rl": "0/1",
    "wheel_on_rumble_strip_rr": "0/1",
    "wheel_in_puddle_fl": "0-1 (1 = flaque la plus profonde)",
    "wheel_in_puddle_fr": "0-1 (1 = flaque la plus profonde)",
    "wheel_in_puddle_rl": "0-1 (1 = flaque la plus profonde)",
    "wheel_in_puddle_rr": "0-1 (1 = flaque la plus profonde)",
    "surface_rumble_fl": "sans dimension",
    "surface_rumble_fr": "sans dimension",
    "surface_rumble_rl": "sans dimension",
    "surface_rumble_rr": "sans dimension",
    "car_ordinal": "identifiant",
    "car_class": "indice 0-7 (4 = S1)",
    "car_performance_index": "PI 100-999",
    "drivetrain_type": "0 = FWD, 1 = RWD, 2 = AWD",
    "num_cylinders": "cylindres",
    "car_category": "indice",
    "horizon_unknown_1": "inconnu (non documente)",
    "horizon_unknown_2": "inconnu (non documente)",
}

DEFAULT_SELECTION: set[str] = {
    # engine_max_rpm sert de reference de mise a l'echelle pour toute jauge
    # de regime : sans lui les consommateurs doivent deviner la zone rouge.
    "speed", "current_engine_rpm", "engine_max_rpm", "gear",
    "accel", "brake", "steer",
    "acceleration_x", "acceleration_y", "acceleration_z",
    "position_x", "position_y", "position_z",
    "yaw", "pitch", "roll",
    "boost", "fuel",
}
