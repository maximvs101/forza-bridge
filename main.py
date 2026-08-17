"""Forza Horizon telemetry bridge (command line).

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

import osc_targets
import smoothing
from bridge import Bridge
from ws_server import TelemetryWebSocketServer


def run(listen_host: str, listen_port: int, targets: list[tuple[str, int]],
        only_racing: bool, ws_host: str = "127.0.0.1", derived: bool = True,
        smoothing_settings=None,
        ws_port: int | None = None, ws_rate_hz: float = 60.0,
        ws_differential: bool = True) -> int:
    ws_server = None
    if ws_port:
        ws_server = TelemetryWebSocketServer(host=ws_host, port=ws_port,
                                             rate_hz=ws_rate_hz,
                                             differential=ws_differential)
        if not ws_server.start():
            print(f"WebSocket server did not start: {ws_server.error}",
                  file=sys.stderr)
            return 1

    bridge = Bridge(
        listen_port=listen_port,
        osc_targets=targets,
        listen_host=listen_host,
        selected_channels=None,  # every channel
        only_racing=only_racing,
        ws_server=ws_server,
        derived=derived,
        smoothing_settings=smoothing_settings,
    )
    bridge.start()
    bridge.bound.wait(timeout=8)
    if bridge.error:
        print(f"Network error: {bridge.error}", file=sys.stderr)
        if ws_server:
            ws_server.stop()
        return 1

    print(f"Listening for Forza UDP on {listen_host}:{listen_port}")
    print(f"Sending OSC to {osc_targets.format_targets(targets)} "
          f"(prefix /forza/...)")
    if ws_server:
        scope = "local network" if ws_host == "0.0.0.0" else "this machine only"
        shown = "localhost" if ws_host == "127.0.0.1" else ws_host
        mode = "differential" if ws_differential else "full frames"
        print(f"WebSocket server on ws://{shown}:{ws_port} "
              f"({ws_rate_hz:g} Hz, {mode}, {scope})")
        print(f"Overlay available at    http://{shown}:{ws_port}/")
    if smoothing_settings:
        print(f"Smoothing: {smoothing.format_settings(smoothing_settings)}")
    print("Press Ctrl+C to stop.\n")

    last_car = None
    last_rejected = 0
    try:
        while bridge.is_alive():
            time.sleep(0.25)
            if bridge.car_name != last_car:
                last_car = bridge.car_name
                print(f"\nVehicle: {last_car}")
            values = bridge.latest_values
            speed_kmh = values.get("speed", 0.0) * 3.6
            rpm = values.get("current_engine_rpm", 0.0)
            line = (f"\rPackets: {bridge.packet_count} | "
                    f"speed: {speed_kmh:6.1f} km/h | rpm: {rpm:6.0f}")
            if ws_server:
                line += f" | WS: {ws_server.client_count} client(s)"
            if bridge.osc_failures:
                line += (" | OSC FAILED: " + ", ".join(
                    osc_targets.format_target(t) for t in bridge.osc_failures))
            print(line, end="", flush=True)

            # Sur une ligne a part, et une seule fois par palier : la ligne de
            # compteurs est reecrite en place, un avertissement noye dedans
            # passerait inapercu.
            refuses = bridge.rejected_summary()
            if refuses and bridge.rejected_count > last_rejected * 2:
                last_rejected = bridge.rejected_count
                print(f"\nWarning: {refuses}", file=sys.stderr)

        # Sortie de boucle sans demande d'arret = le thread est mort seul.
        if bridge.error:
            print(f"\nBridge stopped: {bridge.error}", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        bridge.stop()
        bridge.join(timeout=2)
        if ws_server is not None:
            ws_server.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Parseur isole de main() : l'aide devient verifiable par un test."""
    parser = argparse.ArgumentParser(
        description="Forza Horizon telemetry bridge (UDP -> OSC / WebSocket)")
    parser.add_argument("--listen-host", default="0.0.0.0",
                        help="Address to listen for Forza on (default: 0.0.0.0; "
                             "the game sends from the machine's network address, "
                             "not 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, default=5300,
                        help="Port to listen for Forza on (default: 5300)")
    parser.add_argument("--osc", action="append", metavar="HOST:PORT", default=None,
                        help="OSC destination; repeat it to feed several programs "
                             "at once, or pass a comma-separated list "
                             "(default: 127.0.0.1:7000)")
    # Anciens noms, conserves pour ne pas casser les lancements existants.
    parser.add_argument("--td-host", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--td-port", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--only-racing",
        action="store_true",
        help="Only send data while IsRaceOn=1 (a race is under way)",
    )
    parser.add_argument("--no-derived", action="store_true",
                        help="Send only the game's raw channels, without the "
                             "computed ones (speed_kmh, throttle, g_lateral...)")
    parser.add_argument("--smooth", default="",
                        help="Per-channel smoothing, in seconds: "
                             "\"speed_kmh=0.15, slip_max=0.05\". The larger the "
                             "value, the smoother and the more delayed. Smoothed "
                             "channels are published alongside the raw ones as "
                             "<channel>_smooth.")
    parser.add_argument("--ws-port", type=int, default=8765,
                        help="WebSocket server port (default: 8765, 0 to disable)")
    parser.add_argument("--ws-rate", type=float, default=60.0,
                        help="Maximum WebSocket send rate in Hz "
                             "(default: 60, the source rate)")
    parser.add_argument("--ws-full-frames", action="store_true",
                        help="Send the complete state on every frame instead of "
                             "changes only (for consumers that cannot merge)")
    parser.add_argument("--ws-lan", action="store_true",
                        help="Expose the WebSocket to the whole local network "
                             "(default: this machine only; the stream carries "
                             "the vehicle position)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # `--osc` accepte aussi la liste separee par des virgules, pour que la
    # chaine enregistree par l'interface soit recopiable telle quelle.
    try:
        targets = osc_targets.parse_targets(",".join(args.osc)) if args.osc else []
    except osc_targets.InvalidTarget as exc:
        parser.error(f"--osc: {exc}")

    if args.td_host is not None or args.td_port is not None:
        if targets:
            # Ajouter la cible historique diffuserait la telemetrie, position
            # du vehicule comprise, vers une destination non demandee ici.
            parser.error("--td-host/--td-port are replaced by --osc; "
                         "do not mix the two")
        host = args.td_host if args.td_host is not None else "127.0.0.1"
        port = args.td_port if args.td_port is not None else 7000
        try:
            # Meme validation que --osc : l'ancienne voie ne verifiait rien,
            # et un port hors plage se repliait modulo 65536 en silence.
            targets = [osc_targets.parse_target(
                osc_targets.format_target((host, port)))]
        except osc_targets.InvalidTarget as exc:
            parser.error(f"--td-host/--td-port: {exc}")
        print("Note: --td-host/--td-port are deprecated, use "
              f"--osc {osc_targets.format_targets(targets)}", file=sys.stderr)

    if not targets:
        targets = [osc_targets.DEFAULT_TARGET]

    if args.ws_port and not (0 < args.ws_port <= 65535):
        parser.error("--ws-port must be between 1 and 65535")
    if args.ws_rate <= 0:
        parser.error("--ws-rate must be strictly positive")

    try:
        code = run(args.listen_host, args.listen_port, targets,
                   args.only_racing, derived=not args.no_derived,
                   smoothing_settings=smoothing.parse_settings(args.smooth),
                   ws_host="0.0.0.0" if args.ws_lan else "127.0.0.1",
                   ws_port=args.ws_port, ws_rate_hz=args.ws_rate,
                   ws_differential=not args.ws_full_frames)
    except OSError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
