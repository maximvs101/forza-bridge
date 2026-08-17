"""Passerelle Forza Horizon -> TouchDesigner (ligne de commande).

Ecoute le flux "Data Out" UDP de Forza Horizon, retransmet chaque champ
de telemetrie en OSC vers TouchDesigner (OSC In CHOP) et, si demande,
diffuse la meme telemetrie en WebSocket pour les outils web.

La boucle elle-meme vit dans bridge.py, partagee avec l'interface graphique.

Usage:
    python main.py --listen-port 5300 --td-host 127.0.0.1 --td-port 7000
"""

from __future__ import annotations

import argparse
import sys
import time

from bridge import Bridge
from ws_server import TelemetryWebSocketServer


def run(listen_host: str, listen_port: int, td_host: str, td_port: int,
        only_racing: bool, ws_host: str = "127.0.0.1", derived: bool = True,
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
        td_host=td_host,
        td_port=td_port,
        listen_host=listen_host,
        selected_channels=None,  # tous les champs
        only_racing=only_racing,
        ws_server=ws_server,
        derived=derived,
    )
    bridge.start()
    bridge.bound.wait(timeout=5)
    if bridge.error:
        print(f"Erreur reseau: {bridge.error}", file=sys.stderr)
        if ws_server:
            ws_server.stop()
        return 1

    print(f"Ecoute UDP Forza sur {listen_host}:{listen_port}")
    print(f"Envoi OSC vers TouchDesigner {td_host}:{td_port} (prefixe /forza/...)")
    if ws_server:
        portee = "reseau local" if ws_host == "0.0.0.0" else "cette machine uniquement"
        affichage = "localhost" if ws_host == "127.0.0.1" else ws_host
        mode = "differentiel" if ws_differential else "trames completes"
        print(f"Serveur WebSocket sur ws://{affichage}:{ws_port} "
              f"({ws_rate_hz:g} Hz, {mode}, {portee})")
        print(f"Overlay disponible sur   http://{affichage}:{ws_port}/")
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
    parser = argparse.ArgumentParser(description="Passerelle Forza Horizon -> TouchDesigner (UDP -> OSC/WebSocket)")
    parser.add_argument("--listen-host", default="0.0.0.0",
                        help="Adresse d'ecoute du flux Forza (defaut: 0.0.0.0 ; "
                             "le jeu emet depuis l'adresse reseau de la machine, pas 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, default=5300, help="Port d'ecoute du flux Forza (defaut: 5300)")
    parser.add_argument("--td-host", default="127.0.0.1", help="Adresse de TouchDesigner (defaut: 127.0.0.1)")
    parser.add_argument("--td-port", type=int, default=7000, help="Port OSC In de TouchDesigner (defaut: 7000)")
    parser.add_argument(
        "--only-racing",
        action="store_true",
        help="N'envoie des donnees que lorsque IsRaceOn=1 (course en cours)",
    )
    parser.add_argument("--no-derived", action="store_true",
                        help="N'emet que les canaux bruts du jeu, sans les canaux "
                             "calcules (speed_kmh, throttle, g_lateral...)")
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

    if args.ws_port and not (0 < args.ws_port <= 65535):
        parser.error("--ws-port doit etre compris entre 1 et 65535")
    if args.ws_rate <= 0:
        parser.error("--ws-rate doit etre strictement positif")

    try:
        code = run(args.listen_host, args.listen_port, args.td_host, args.td_port,
                   args.only_racing, derived=not args.no_derived,
                   ws_host="0.0.0.0" if args.ws_lan else "127.0.0.1",
                   ws_port=args.ws_port, ws_rate_hz=args.ws_rate,
                   ws_differential=not args.ws_full_frames)
    except OSError as exc:
        print(f"Erreur reseau: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
