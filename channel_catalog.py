"""Catalogue des canaux de telemetrie exposes dans l'interface.

Les noms de categories et les libelles d'unites sont AFFICHES (interface,
table TouchDesigner, message d'accueil WebSocket) : ils sont donc en anglais,
comme le reste de ce que voit l'utilisateur.

Regroupe les champs de forza_telemetry.py par categorie pour l'affichage,
et definit une selection par defaut ("essentiels") pour un demarrage rapide.
Sert aussi a publier les unites dans le message d'accueil WebSocket.
"""

from derived_channels import DERIVED_CHANNELS, DERIVED_UNITS

CATEGORIES: dict[str, list[str]] = {
    "General": ["is_race_on", "timestamp_ms"],
    "Engine": ["engine_max_rpm", "engine_idle_rpm", "current_engine_rpm"],
    "Motion": [
        "acceleration_x", "acceleration_y", "acceleration_z",
        "velocity_x", "velocity_y", "velocity_z",
        "angular_velocity_x", "angular_velocity_y", "angular_velocity_z",
        "yaw", "pitch", "roll",
    ],
    "Position / race": [
        "position_x", "position_y", "position_z",
        "speed", "power", "torque",
        "distance_traveled", "best_lap_time", "last_lap_time",
        "current_lap_time", "current_race_time", "lap_number", "race_position",
    ],
    "Controls": [
        "accel", "brake", "clutch", "hand_brake", "gear",
        "steer", "norm_driving_line", "norm_ai_brake_difference", "boost", "fuel",
    ],
    "Suspension": [
        "norm_suspension_travel_fl", "norm_suspension_travel_fr",
        "norm_suspension_travel_rl", "norm_suspension_travel_rr",
        "suspension_travel_meters_fl", "suspension_travel_meters_fr",
        "suspension_travel_meters_rl", "suspension_travel_meters_rr",
    ],
    "Tyres": [
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
    "Vehicle": [
        "car_ordinal", "car_class", "car_performance_index",
        "drivetrain_type", "num_cylinders", "car_category",
    ],
    # Champs presents dans le paquet Horizon mais jamais identifies par la
    # communaute. Ils etaient auparavant absents du catalogue tout en etant
    # emis par main.py : deux canaux etaient donc diffuses sans figurer
    # dans aucune liste. Listes ici, et decoches par defaut.
    "Undocumented": [
        "horizon_unknown_1", "horizon_unknown_2",
    ],
}

# Canaux bruts, tels que decodes du paquet Forza.
RAW_CHANNELS: list[str] = [name for names in CATEGORIES.values() for name in names]

# Canaux calcules par le pont (unites usuelles, grandeurs bornees). Ajoutes au
# catalogue pour apparaitre dans l'interface et le message d'accueil comme
# n'importe quel autre canal.
CATEGORIES["Derived"] = list(DERIVED_CHANNELS)

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
    "current_engine_rpm": "rpm",
    "engine_max_rpm": "rpm",
    "engine_idle_rpm": "rpm",
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
    "gear": "gear (0 = reverse)",
    "timestamp_ms": "ms",
    "is_race_on": "0/1",

    # Grandeurs sans dimension : le declarer explicitement evite qu'un
    # consommateur confonde "sans unite" et "unite oubliee".
    "boost": "dimensionless",
    "fuel": "fraction 0-1",
    "lap_number": "lap number",
    "race_position": "position",
    "norm_suspension_travel_fl": "0-1 (0 = full extension, 1 = full compression)",
    "norm_suspension_travel_fr": "0-1 (0 = full extension, 1 = full compression)",
    "norm_suspension_travel_rl": "0-1 (0 = full extension, 1 = full compression)",
    "norm_suspension_travel_rr": "0-1 (0 = full extension, 1 = full compression)",
    "tire_slip_ratio_fl": "normalised (|x| > 1 = grip loss)",
    "tire_slip_ratio_fr": "normalised (|x| > 1 = grip loss)",
    "tire_slip_ratio_rl": "normalised (|x| > 1 = grip loss)",
    "tire_slip_ratio_rr": "normalised (|x| > 1 = grip loss)",
    "tire_slip_angle_fl": "normalised (|x| > 1 = grip loss)",
    "tire_slip_angle_fr": "normalised (|x| > 1 = grip loss)",
    "tire_slip_angle_rl": "normalised (|x| > 1 = grip loss)",
    "tire_slip_angle_rr": "normalised (|x| > 1 = grip loss)",
    "tire_combined_slip_fl": "normalised (|x| > 1 = grip loss)",
    "tire_combined_slip_fr": "normalised (|x| > 1 = grip loss)",
    "tire_combined_slip_rl": "normalised (|x| > 1 = grip loss)",
    "tire_combined_slip_rr": "normalised (|x| > 1 = grip loss)",
    "wheel_on_rumble_strip_fl": "0/1",
    "wheel_on_rumble_strip_fr": "0/1",
    "wheel_on_rumble_strip_rl": "0/1",
    "wheel_on_rumble_strip_rr": "0/1",
    "wheel_in_puddle_fl": "0-1 (1 = deepest puddle)",
    "wheel_in_puddle_fr": "0-1 (1 = deepest puddle)",
    "wheel_in_puddle_rl": "0-1 (1 = deepest puddle)",
    "wheel_in_puddle_rr": "0-1 (1 = deepest puddle)",
    "surface_rumble_fl": "dimensionless",
    "surface_rumble_fr": "dimensionless",
    "surface_rumble_rl": "dimensionless",
    "surface_rumble_rr": "dimensionless",
    "car_ordinal": "identifier",
    "car_class": "index 0-7 (4 = S1)",
    "car_performance_index": "PI 100-999",
    "drivetrain_type": "0 = FWD, 1 = RWD, 2 = AWD",
    "num_cylinders": "cylinders",
    "car_category": "index",
    "horizon_unknown_1": "unknown (undocumented)",
    "horizon_unknown_2": "unknown (undocumented)",
}

# Unites des canaux calcules par le pont.
UNITS.update(DERIVED_UNITS)

DEFAULT_SELECTION: set[str] = {
    # engine_max_rpm sert de reference de mise a l'echelle pour toute jauge
    # de regime : sans lui les consommateurs doivent deviner la zone rouge.
    "speed", "current_engine_rpm", "engine_max_rpm", "gear",
    # Canaux derives : bornes et en unites usuelles, ils evitent aux
    # consommateurs de refaire les memes conversions.
    "speed_kmh", "rpm_ratio", "throttle", "brake_pedal", "steer_norm",
    "g_lateral", "g_longitudinal", "slip_max",
    "accel", "brake", "steer",
    "acceleration_x", "acceleration_y", "acceleration_z",
    "position_x", "position_y", "position_z",
    "yaw", "pitch", "roll",
    "boost", "fuel",
}
