"""Parseur du flux UDP "Data Out" de Forza Horizon.

Format "Horizon Dash" (sled + extension Horizon + dash), tel qu'utilise
par FH4/FH5 et repris par FH6. Reference: FH4_packetformat.dat
(projet richstokes/Forza-data-tools) + doc officielle Forza Support.

Trois tailles de paquet sont acceptees :
  - 232 octets : "sled" seul (rare, generalement desactive dans les options)
  - 323 octets : "dash" Horizon complet
  - 324 octets : "dash" Horizon + 1 octet de fin (paquets recents)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_SLED_FIELDS = [
    ("is_race_on", "i"), ("timestamp_ms", "I"),
    ("engine_max_rpm", "f"), ("engine_idle_rpm", "f"), ("current_engine_rpm", "f"),
    ("acceleration_x", "f"), ("acceleration_y", "f"), ("acceleration_z", "f"),
    ("velocity_x", "f"), ("velocity_y", "f"), ("velocity_z", "f"),
    ("angular_velocity_x", "f"), ("angular_velocity_y", "f"), ("angular_velocity_z", "f"),
    ("yaw", "f"), ("pitch", "f"), ("roll", "f"),
    ("norm_suspension_travel_fl", "f"), ("norm_suspension_travel_fr", "f"),
    ("norm_suspension_travel_rl", "f"), ("norm_suspension_travel_rr", "f"),
    ("tire_slip_ratio_fl", "f"), ("tire_slip_ratio_fr", "f"),
    ("tire_slip_ratio_rl", "f"), ("tire_slip_ratio_rr", "f"),
    ("wheel_rotation_speed_fl", "f"), ("wheel_rotation_speed_fr", "f"),
    ("wheel_rotation_speed_rl", "f"), ("wheel_rotation_speed_rr", "f"),
    ("wheel_on_rumble_strip_fl", "i"), ("wheel_on_rumble_strip_fr", "i"),
    ("wheel_on_rumble_strip_rl", "i"), ("wheel_on_rumble_strip_rr", "i"),
    ("wheel_in_puddle_fl", "f"), ("wheel_in_puddle_fr", "f"),
    ("wheel_in_puddle_rl", "f"), ("wheel_in_puddle_rr", "f"),
    ("surface_rumble_fl", "f"), ("surface_rumble_fr", "f"),
    ("surface_rumble_rl", "f"), ("surface_rumble_rr", "f"),
    ("tire_slip_angle_fl", "f"), ("tire_slip_angle_fr", "f"),
    ("tire_slip_angle_rl", "f"), ("tire_slip_angle_rr", "f"),
    ("tire_combined_slip_fl", "f"), ("tire_combined_slip_fr", "f"),
    ("tire_combined_slip_rl", "f"), ("tire_combined_slip_rr", "f"),
    ("suspension_travel_meters_fl", "f"), ("suspension_travel_meters_fr", "f"),
    ("suspension_travel_meters_rl", "f"), ("suspension_travel_meters_rr", "f"),
    ("car_ordinal", "i"), ("car_class", "i"), ("car_performance_index", "i"),
    ("drivetrain_type", "i"), ("num_cylinders", "i"),
]

_HORIZON_EXTRA_FIELDS = [
    ("car_category", "i"), ("horizon_unknown_1", "I"), ("horizon_unknown_2", "I"),
]

_DASH_FIELDS = [
    ("position_x", "f"), ("position_y", "f"), ("position_z", "f"),
    ("speed", "f"), ("power", "f"), ("torque", "f"),
    ("tire_temp_fl", "f"), ("tire_temp_fr", "f"),
    ("tire_temp_rl", "f"), ("tire_temp_rr", "f"),
    ("boost", "f"), ("fuel", "f"), ("distance_traveled", "f"),
    ("best_lap_time", "f"), ("last_lap_time", "f"),
    ("current_lap_time", "f"), ("current_race_time", "f"),
    ("lap_number", "H"),
    ("race_position", "B"), ("accel", "B"), ("brake", "B"),
    ("clutch", "B"), ("hand_brake", "B"), ("gear", "B"),
    ("steer", "b"), ("norm_driving_line", "b"), ("norm_ai_brake_difference", "b"),
]

_SLED_ONLY = _SLED_FIELDS
_HORIZON_DASH = _SLED_FIELDS + _HORIZON_EXTRA_FIELDS + _DASH_FIELDS

_SLED_FORMAT = "<" + "".join(t for _, t in _SLED_ONLY)
_HORIZON_DASH_FORMAT = "<" + "".join(t for _, t in _HORIZON_DASH)

SLED_SIZE = struct.calcsize(_SLED_FORMAT)          # 232
HORIZON_DASH_SIZE = struct.calcsize(_HORIZON_DASH_FORMAT)  # 323 (+1 octet parfois)

assert SLED_SIZE == 232
assert HORIZON_DASH_SIZE == 323


@dataclass
class TelemetryFrame:
    is_race_on: bool
    values: dict[str, float]


def parse(packet: bytes) -> TelemetryFrame | None:
    """Parse un paquet UDP Forza. Renvoie None si la taille est inconnue."""
    n = len(packet)

    # Tailles acceptees strictement : un `>=` laissait passer n'importe quel
    # datagramme etranger de 323 octets ou plus (bavardage reseau, autre jeu)
    # et le decodait en flottants aberrants, aussitot diffuses en OSC.
    # Mesure sur FH6 (aout 2026) : les paquets font 324 octets.
    if n in (HORIZON_DASH_SIZE, HORIZON_DASH_SIZE + 1):
        fields, fmt = _HORIZON_DASH, _HORIZON_DASH_FORMAT
    elif n == SLED_SIZE:
        fields, fmt = _SLED_ONLY, _SLED_FORMAT
    else:
        return None

    raw = struct.unpack(fmt, packet[:struct.calcsize(fmt)])
    values = {name: value for (name, _), value in zip(fields, raw)}
    return TelemetryFrame(is_race_on=bool(values["is_race_on"]), values=values)
