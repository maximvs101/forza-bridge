"""Constructeur du composant TouchDesigner 'Forza Bridge'.

A executer UNE FOIS depuis un Text DAT (langage Python) dans TouchDesigner,
avec ce DAT place a l'endroit ou le composant doit apparaitre (ex: /project1).

Ce script cree un Base COMP nommé 'forza_bridge' contenant :
  - oscin1  : OSC In CHOP, port configurable via le parametre custom "Port"
              du composant (defaut 7000), avec Strip Prefix Segments = 1
              pour transformer "/forza/speed" en canal "speed" directement.
  - null1   : Null CHOP, sortie propre du composant (a cabler ailleurs).
  - channel_docs : Table DAT listant tous les canaux connus (categorie + nom),
              pour reference dans le reseau.

Le composant est ensuite sauvegarde en .tox a cote du projet courant,
pour pouvoir etre glisse-depose (drag & drop) dans n'importe quel autre
projet TouchDesigner comme un vrai plugin reutilisable.

Correspond a la passerelle Python du dossier forza-bridge (main.py / gui.py),
qui envoie chaque champ de telemetrie Forza en OSC sous l'adresse /forza/<champ>.
"""

# Catalogue des canaux (categorie -> liste de noms), duplique ici depuis
# channel_catalog.py pour que ce script reste autonome (pas de dependance
# a un chemin Python externe au reseau TouchDesigner).
CATEGORIES = {
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
    # Presents dans le paquet mais jamais identifies par la communaute.
    "Undocumented": [
        "horizon_unknown_1", "horizon_unknown_2",
    ],
    # Calcules par la passerelle : unites usuelles et grandeurs bornees,
    # directement exploitables sans conversion cote TouchDesigner.
    "Derived": [
        "speed_kmh", "speed_mph", "rpm_ratio",
        "throttle", "brake_pedal", "clutch_pedal", "handbrake_pedal", "steer_norm",
        "g_lateral", "g_vertical", "g_longitudinal",
        "yaw_deg", "pitch_deg", "roll_deg",
        "tire_temp_fl_c", "tire_temp_fr_c", "tire_temp_rl_c", "tire_temp_rr_c",
        "slip_max", "shifting",
    ],
}


def build(destination=None):
    """Construit le composant 'forza_bridge' dans `destination` (defaut: parent() du DAT)."""
    container = destination if destination is not None else parent()

    if op(container.path + '/forza_bridge') is not None:
        op(container.path + '/forza_bridge').destroy()

    comp = container.create(baseCOMP, 'forza_bridge')
    comp.nodeX, comp.nodeY = 0, 0
    comp.viewer = True

    page = comp.appendCustomPage('Forza')
    port_par = page.appendInt('Port')[0]
    port_par.val = 7000
    port_par.label = 'OSC port (must match the Python bridge)'

    oscin1 = comp.create(oscinCHOP, 'oscin1')
    oscin1.nodeX, oscin1.nodeY = 0, 200
    oscin1.par.port.expr = "parent().par.Port"
    oscin1.par.active = True
    oscin1.par.stripsegments = 1  # "/forza/speed" -> canal "speed"

    null1 = comp.create(nullCHOP, 'null1')
    null1.nodeX, null1.nodeY = 0, 100
    null1.inputConnectors[0].connect(oscin1)
    null1.viewer = True

    docs = comp.create(tableDAT, 'channel_docs')
    docs.nodeX, docs.nodeY = -300, 100
    docs.clear()
    docs.appendRow(['category', 'channel'])
    for category, names in CATEGORIES.items():
        for name in names:
            docs.appendRow([category, name])

    info = comp.create(textDAT, 'readme')
    info.nodeX, info.nodeY = -300, 200
    info.text = (
        "Forza Bridge - component output: null1 (CHOP)\n"
        "Set the 'Port' parameter (Forza page) to match the OSC\n"
        "destination of the Python bridge:\n"
        "  main.py --osc 127.0.0.1:<port>\n"
        "  or the 'Destinations' field in gui.py\n"
        "See channel_docs for the list of available channels."
    )

    if project.folder:
        tox_path = project.folder + '/forza_bridge.tox'
        comp.save(tox_path)
        print('Component saved: ' + tox_path)

    print('forza_bridge built successfully (' + str(len(comp.children)) + ' internal operators).')
    return comp


build()
