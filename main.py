"""Passerelle de telemetrie Forza Horizon (ligne de commande).

Ecoute le flux "Data Out" UDP de Forza Horizon, retransmet chaque champ
de telemetrie en OSC vers une ou plusieurs destinations, et diffuse la meme
telemetrie en WebSocket pour les outils web.

Compatible avec tout logiciel parlant OSC ou WebSocket : creation visuelle
(TouchDesigner, cables.gl, vvvv), lumiere (QLC+, Chataigne), son
(SuperCollider, Pure Data, Sonic Pi), overlay de diffusion.

La boucle elle-meme vit dans bridge.py, partagee avec l'interface graphique.

Usage:
    python main.py
    python main.py --osc 127.0.0.1:7000 --osc 192.168.0.50:9000
"""

from __future__ import annotations

import argparse
import sys
import time

import smoothing
from bridge import Bridge
from ws_server import TelemetryWebSocketServer


def run(listen_host: str, listen_port: int, osc_targets: list[tuple[str, int]],
        only_racing: bool, ws_host: str = "127.0.0.1", derived: bool = True,
        smoothing_settings=None,
        ws_port: int | None = None, ws_rate_hz: float = 60.0,
        ws_differential: bool = True) -> int:
    ws_server = None
    if ws_port:
        ws_server = TelemetryWebSocketServer(host=ws_host, port=ws_port, rate_hz=ws_rate_hz,
                                             differential=ws_differential)
        if not ws_server.start():
            print(f"Serveur WebSocket non demarre: {ws_server.error}", file=sys.stderr)
            return 1

    bridge = Bridge(
        listen_port=listen_port,
        osc_targets=osc_targets,
        listen_host=listen_host,
        selected_channels=None,  # tous les champs
        only_racing=only_racing,
        ws_server=ws_server,
        derived=derived,
        smoothing_settings=smoothing_settings,
    )
    bridge.start()
    bridge.bound.wait(timeout=5)
    if bridge.error:
        print(f"Erreur reseau: {bridge.error}", file=sys.stderr)
        if ws_server:
            ws_server.stop()
        return 1

    print(f"Ecoute UDP Forza sur {listen_host}:{listen_port}")
    destinations = ", ".join(f"{hote}:{port}" for hote, port in osc_targets)
    print(f"Envoi OSC vers {destinations} (prefixe /forza/...)")
    if ws_server:
        portee = "reseau local" if ws_host == "0.0.0.0" else "cette machine uniquement"
        affichage = "localhost" if ws_host == "127.0.0.1" else ws_host
        mode = "differentiel" if ws_differential else "trames completes"
        print(f"Serveur WebSocket sur ws://{affichage}:{ws_port} "
              f"({ws_rate_hz:g} Hz, {mode}, {portee})")
        print(f"Overlay disponible sur   http://{affichage}:{ws_port}/")
    if smoothing_settings:
        print(f"Lissage : {smoothing.formate_reglages(smoothing_settings)}")
    print("Ctrl+C pour arreter.\n")

    last_car = None
    try:
        while bridge.is_alive():
            time.sleep(0.25)
            if bridge.car_name != last_car:
                last_car = bridge.car_name
                print(f"\nVehicule: {last_car}")
            values = bridge.latest_values
            speed_kmh = values.get("speed", 0.0) * 3.6
            rpm = values.get("current_engine_rpm", 0.0)
            line = (f"\rPaquets recus: {bridge.packet_count} | "
                    f"vitesse: {speed_kmh:6.1f} km/h | RPM: {rpm:6.0f}")
            if ws_server:
                line += f" | WS: {ws_server.client_count} client(s)"
            print(line, end="", flush=True)

        # Sortie de boucle sans demande d'arret = le thread est mort seul.
        if bridge.error:
            print(f"\nArret du pont: {bridge.error}", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print("\nArret.")
    finally:
        bridge.stop()
        bridge.join(timeout=2)
        if ws_server is not None:
            ws_server.stop()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Passerelle de telemetrie Forza Horizon (UDP -> OSC / WebSocket)")
    parser.add_argument("--listen-host", default="0.0.0.0",
                        help="Adresse d'ecoute du flux Forza (defaut: 0.0.0.0 ; "
                             "le jeu emet depuis l'adresse reseau de la machine, pas 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, default=5300, help="Port d'ecoute du flux Forza (defaut: 5300)")
    parser.add_argument("--osc", action="append", metavar="HOTE:PORT", default=None,
                        help="Destination OSC, repetable pour alimenter plusieurs "
                             "logiciels a la fois (defaut: 127.0.0.1:7000)")
    # Anciens noms, conserves pour ne pas casser les lancements existants.
    parser.add_argument("--td-host", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--td-port", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--only-racing",
        action="store_true",
        help="N'envoie des donnees que lorsque IsRaceOn=1 (course en cours)",
    )
    parser.add_argument("--no-derived", action="store_true",
                        help="N'emet que les canaux bruts du jeu, sans les canaux "
                             "calcules (speed_kmh, throttle, g_lateral...)")
    parser.add_argument("--smooth", default="",
                        help="Lissage par canal, en secondes : "
                             "\"speed_kmh=0.15, slip_max=0.05\". Plus la valeur est "
                             "grande, plus c'est lisse et plus c'est en retard.")
    parser.add_argument("--ws-port", type=int, default=8765,
                        help="Port du serveur WebSocket (defaut: 8765, 0 pour desactiver)")
    parser.add_argument("--ws-rate", type=float, default=60.0,
                        help="Cadence max d'emission WebSocket en Hz (defaut: 60, cadence de la source)")
    parser.add_argument("--ws-full-frames", action="store_true",
                        help="Envoie l'etat complet a chaque trame au lieu des seules "
                             "variations (pour un consommateur qui ne sait pas fusionner)")
    parser.add_argument("--ws-lan", action="store_true",
                        help="Expose le WebSocket a tout le reseau local "
                             "(defaut: cette machine uniquement ; le flux contient la position du vehicule)")
    args = parser.parse_args()

    cibles = []
    for entree in (args.osc or []):
        hote, separateur, port = entree.rpartition(":")
        if not separateur or not port.isdigit() or not (0 < int(port) <= 65535):
            parser.error(f"--osc attend HOTE:PORT, recu \"{entree}\"")
        cibles.append((hote, int(port)))
    if args.td_host is not None or args.td_port is not None:
        cibles.append((args.td_host or "127.0.0.1", args.td_port or 7000))
    if not cibles:
        cibles.append(("127.0.0.1", 7000))

    if args.ws_port and not (0 < args.ws_port <= 65535):
        parser.error("--ws-port doit etre compris entre 1 et 65535")
    if args.ws_rate <= 0:
        parser.error("--ws-rate doit etre strictement positif")

    try:
        code = run(args.listen_host, args.listen_port, cibles,
                   args.only_racing, derived=not args.no_derived,
                   smoothing_settings=smoothing.parse_reglages(args.smooth),
                   ws_host="0.0.0.0" if args.ws_lan else "127.0.0.1",
                   ws_port=args.ws_port, ws_rate_hz=args.ws_rate,
                   ws_differential=not args.ws_full_frames)
    except OSError as exc:
        print(f"Erreur reseau: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
