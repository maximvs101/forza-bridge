"""Interface graphique pour la passerelle Forza Horizon -> TouchDesigner.

Permet de configurer la connexion UDP/OSC, choisir les canaux a transmettre,
et visualiser les valeurs recues en temps reel.

Lancement: python gui.py
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import car_lookup
import smoothing
import tray
from bridge import Bridge
from channel_catalog import CATEGORIES, DEFAULT_SELECTION
from ws_server import TelemetryWebSocketServer

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config() -> dict:
    default = {
        "listen_port": 5300,
        "td_host": "127.0.0.1",
        "td_port": 7000,
        "only_racing": False,
        "send_car_name": True,
        "ws_enabled": True,
        "ws_lan": False,
        "derived": True,
        "smoothing": "",
        "tray": True,
        "ws_differential": True,
        "ws_port": 8765,
        "ws_rate_hz": 60,
        "selected_channels": sorted(DEFAULT_SELECTION),
    }
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            default.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def save_config(config: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class BridgeGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Passerelle Forza Horizon -> TouchDesigner")
        self.config_data = load_config()
        self.selected_channels: set[str] = set(self.config_data["selected_channels"])
        self.bridge: Bridge | None = None
        self.ws_server: TelemetryWebSocketServer | None = None
        self.row_by_channel: dict[str, str] = {}
        self.tray: tray.TrayIcon | None = None
        self._quitting = False
        self._last_speed = 0.0

        self._build_config_frame()
        self._build_vehicle_frame()
        self._build_channel_frame()
        self._build_status_bar()

        self._apply_smoothing()
        self._setup_tray()
        # Fermer la fenetre replie dans la barre d'etat plutot que d'arreter
        # le pont : c'est un outil qu'on laisse tourner pendant qu'on joue.
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._refresh_loop()

    # -- construction de l'interface -----------------------------------

    def _build_config_frame(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Connexion")
        frame.pack(fill="x", padx=8, pady=6)

        ttk.Label(frame, text="Port d'ecoute Forza:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.listen_port_var = tk.StringVar(value=str(self.config_data["listen_port"]))
        ttk.Entry(frame, textvariable=self.listen_port_var, width=8).grid(row=0, column=1, padx=4)

        ttk.Label(frame, text="IP TouchDesigner:").grid(row=0, column=2, sticky="w", padx=4)
        self.td_host_var = tk.StringVar(value=self.config_data["td_host"])
        ttk.Entry(frame, textvariable=self.td_host_var, width=14).grid(row=0, column=3, padx=4)

        ttk.Label(frame, text="Port OSC TouchDesigner:").grid(row=0, column=4, sticky="w", padx=4)
        self.td_port_var = tk.StringVar(value=str(self.config_data["td_port"]))
        ttk.Entry(frame, textvariable=self.td_port_var, width=8).grid(row=0, column=5, padx=4)

        self.only_racing_var = tk.BooleanVar(value=self.config_data["only_racing"])
        ttk.Checkbutton(
            frame, text="Envoyer seulement en course (IsRaceOn)", variable=self.only_racing_var
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=4)

        self.send_car_name_var = tk.BooleanVar(value=self.config_data["send_car_name"])
        ttk.Checkbutton(
            frame,
            text="Envoyer /forza/car_name en OSC (chaine -> OSC In DAT)",
            variable=self.send_car_name_var,
            command=self._on_send_car_name_toggled,
        ).grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 4))

        self.start_button = ttk.Button(frame, text="Demarrer", command=self._toggle_worker)
        self.start_button.grid(row=1, column=5, sticky="e", padx=4, pady=4)

        # -- sortie WebSocket (outils web : cables.gl, overlay OBS, three.js...)
        self.ws_enabled_var = tk.BooleanVar(value=self.config_data["ws_enabled"])
        ttk.Checkbutton(
            frame, text="Serveur WebSocket", variable=self.ws_enabled_var
        ).grid(row=3, column=0, sticky="w", padx=4, pady=(0, 6))

        ttk.Label(frame, text="port:").grid(row=3, column=1, sticky="e", padx=2)
        self.ws_port_var = tk.StringVar(value=str(self.config_data["ws_port"]))
        ttk.Entry(frame, textvariable=self.ws_port_var, width=8).grid(row=3, column=2, sticky="w", padx=2)

        ttk.Label(frame, text="cadence (Hz):").grid(row=3, column=3, sticky="e", padx=2)
        self.ws_rate_var = tk.StringVar(value=str(self.config_data["ws_rate_hz"]))
        ttk.Entry(frame, textvariable=self.ws_rate_var, width=6).grid(row=3, column=4, sticky="w", padx=2)

        self.ws_lan_var = tk.BooleanVar(value=self.config_data["ws_lan"])
        ttk.Checkbutton(
            frame,
            text="Ouvrir le WebSocket au reseau local (sinon cette machine uniquement)",
            variable=self.ws_lan_var,
        ).grid(row=4, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 2))

        self.derived_var = tk.BooleanVar(value=self.config_data["derived"])
        ttk.Checkbutton(
            frame,
            text="Canaux derives (speed_kmh, throttle, g_lateral... deja mis a l'echelle)",
            variable=self.derived_var,
        ).grid(row=2, column=4, columnspan=2, sticky="w", padx=4, pady=(0, 4))

        self.ws_differential_var = tk.BooleanVar(value=self.config_data["ws_differential"])
        ttk.Checkbutton(
            frame,
            text="Emission differentielle (n'envoyer que les variations ; le client doit fusionner)",
            variable=self.ws_differential_var,
        ).grid(row=5, column=0, columnspan=6, sticky="w", padx=4, pady=(0, 6))

        ttk.Label(frame, text="Lissage (s):").grid(row=6, column=0, sticky="w", padx=4, pady=(0, 6))
        self.smoothing_var = tk.StringVar(value=self.config_data["smoothing"])
        ttk.Entry(frame, textvariable=self.smoothing_var, width=52).grid(
            row=6, column=1, columnspan=4, sticky="we", padx=4, pady=(0, 6))
        ttk.Button(frame, text="Appliquer", command=self._apply_smoothing).grid(
            row=6, column=5, sticky="e", padx=4, pady=(0, 6))

    def _build_vehicle_frame(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Vehicule detecte")
        frame.pack(fill="x", padx=8, pady=(0, 6))

        self.car_name_var = tk.StringVar(value="-")
        ttk.Label(frame, textvariable=self.car_name_var, font=("Segoe UI", 11, "bold")).pack(
            side="left", padx=6, pady=5
        )
        self.car_detail_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.car_detail_var, foreground="#555").pack(side="left", padx=6)

    def _build_channel_frame(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Canaux a transmettre")
        frame.pack(fill="both", expand=True, padx=8, pady=6)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", padx=4, pady=4)

        ttk.Label(toolbar, text="Filtrer:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(toolbar, textvariable=self.filter_var, width=20).pack(side="left", padx=4)

        ttk.Button(toolbar, text="Tout cocher", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Tout decocher", command=self._select_none).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Selection recommandee", command=self._select_default).pack(side="left", padx=4)

        columns = ("select", "category", "channel", "smooth", "value")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none")
        self.tree.heading("select", text="")
        self.tree.heading("category", text="Categorie")
        self.tree.heading("channel", text="Canal")
        self.tree.heading("smooth", text="Lissage")
        self.tree.heading("value", text="Valeur")
        self.tree.column("select", width=30, anchor="center")
        self.tree.column("category", width=130, anchor="w")
        self.tree.column("channel", width=240, anchor="w")
        self.tree.column("smooth", width=70, anchor="e")
        self.tree.column("value", width=100, anchor="e")
        self.tree.pack(fill="both", expand=True, side="left", padx=4, pady=4)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.bind("<Button-1>", self._on_tree_click)

        for category, names in CATEGORIES.items():
            for name in names:
                checked = "☑" if name in self.selected_channels else "☐"
                row_id = self.tree.insert("", "end", values=(checked, category, name, "", ""))
                self.row_by_channel[name] = row_id

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar(value="Arrete.")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=(0, 6))

    # -- actions ----------------------------------------------------------

    def _apply_filter(self) -> None:
        needle = self.filter_var.get().strip().lower()
        for name, row_id in self.row_by_channel.items():
            category = self.tree.set(row_id, "category").lower()
            visible = needle in name.lower() or needle in category
            self.tree.reattach(row_id, "", "end") if visible else self.tree.detach(row_id)

    def _set_all(self, selected: bool) -> None:
        for name, row_id in self.row_by_channel.items():
            if selected:
                self.selected_channels.add(name)
            else:
                self.selected_channels.discard(name)
            self.tree.set(row_id, "select", "☑" if selected else "☐")
        self._push_selection()

    def _select_all(self) -> None:
        self._set_all(True)

    def _select_none(self) -> None:
        self._set_all(False)

    def _select_default(self) -> None:
        self.selected_channels = set(DEFAULT_SELECTION)
        for name, row_id in self.row_by_channel.items():
            self.tree.set(row_id, "select", "☑" if name in self.selected_channels else "☐")
        self._push_selection()

    def _on_tree_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        name = self.tree.set(row_id, "channel")
        if name in self.selected_channels:
            self.selected_channels.discard(name)
            self.tree.set(row_id, "select", "☐")
        else:
            self.selected_channels.add(name)
            self.tree.set(row_id, "select", "☑")
        self._push_selection()

    def _push_selection(self) -> None:
        """Transmet la selection au thread reseau.

        On affecte un NOUVEL ensemble fige : le thread en prend un instantane
        a chaque trame. Muter en place l'objet qu'il itere levait
        "Set changed size during iteration" et tuait le thread en silence
        (cocher une case pendant la reception suffisait).
        """
        if self.bridge:
            self.bridge.selected_channels = frozenset(self.selected_channels)

    def _setup_tray(self) -> None:
        if not self.config_data.get("tray", True):
            return
        self.tray = tray.TrayIcon(
            on_show=lambda: self.root.after(0, self._show_window),
            on_start_stop=lambda: self.root.after(0, self._toggle_worker),
            on_open_overlay=lambda: self.root.after(0, self._open_overlay),
            on_quit=lambda: self.root.after(0, self._quit),
        )
        if not self.tray.start():
            self.tray = None  # dependance absente : on reste une fenetre ordinaire

    def _hide_to_tray(self) -> None:
        if self.tray is None:
            self._quit()
            return
        self.root.withdraw()

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def _open_overlay(self) -> None:
        import webbrowser
        try:
            port = int(self.ws_port_var.get())
        except ValueError:
            port = 8765
        webbrowser.open(f"http://localhost:{port}/")

    def _quit(self) -> None:
        self._quitting = True
        self._on_close()

    def _refresh_tray(self) -> None:
        if self.tray is None:
            return
        vitesse = 0.0
        if self.bridge is not None:
            vitesse = self.bridge.latest_values.get("speed", 0.0) or 0.0
        etat = tray.etat_pont(self.bridge, en_mouvement=vitesse > 0.5)
        self.tray.update(etat, self.bridge)

    def _apply_smoothing(self) -> None:
        """Relit le champ de lissage et l'applique, pont en marche ou non."""
        reglages = smoothing.parse_reglages(self.smoothing_var.get())
        # Reaffiche la forme normalisee : l'utilisateur voit ce qui a ete
        # retenu, et donc ce qui a ete ignore (canal non lissable, valeur
        # invalide).
        self.smoothing_var.set(smoothing.formate_reglages(reglages))
        for name, row_id in self.row_by_channel.items():
            tau = reglages.get(name)
            self.tree.set(row_id, "smooth", f"{tau:g} s" if tau else "")
        if self.bridge:
            self.bridge.smoother.configure(reglages)

        # Un nom mal orthographie ne s'appliquerait a rien, en silence.
        inconnus = sorted(n for n in reglages if n not in self.row_by_channel)
        if inconnus:
            self.status_var.set(
                f"Lissage applique a {len(reglages) - len(inconnus)} canal(aux). "
                f"Canaux inconnus ignores : {', '.join(inconnus)}")
        else:
            self.status_var.set(
                f"Lissage applique a {len(reglages)} canal(aux)." if reglages
                else "Lissage desactive.")

    def _on_send_car_name_toggled(self) -> None:
        if self.bridge:
            self.bridge.send_car_name = self.send_car_name_var.get()

    def _toggle_worker(self) -> None:
        if self.bridge is None:
            self._start_worker()
        else:
            self._stop_worker()

    def _read_port(self, var: tk.StringVar, label: str) -> int | None:
        """Lit un port et verifie sa plage. None si invalide (message affiche)."""
        try:
            value = int(var.get())
        except ValueError:
            self.status_var.set(f"{label} invalide.")
            return None
        if not (0 < value <= 65535):
            self.status_var.set(f"{label} hors plage (1-65535).")
            return None
        return value

    def _start_worker(self) -> None:
        listen_port = self._read_port(self.listen_port_var, "Port d'ecoute Forza")
        if listen_port is None:
            return
        td_port = self._read_port(self.td_port_var, "Port OSC TouchDesigner")
        if td_port is None:
            return

        if self.ws_enabled_var.get():
            ws_port = self._read_port(self.ws_port_var, "Port WebSocket")
            if ws_port is None:
                return
            try:
                ws_rate = float(self.ws_rate_var.get())
            except ValueError:
                self.status_var.set("Cadence WebSocket invalide.")
                return
            if ws_rate <= 0:
                self.status_var.set("La cadence WebSocket doit etre positive.")
                return
            # Ecoute locale sauf demande explicite : le flux contient la
            # position du vehicule.
            ws_host = "0.0.0.0" if self.ws_lan_var.get() else "127.0.0.1"
            self.ws_server = TelemetryWebSocketServer(
                host=ws_host, port=ws_port, rate_hz=ws_rate,
                differential=self.ws_differential_var.get())
            if not self.ws_server.start():
                self.status_var.set(f"Erreur WebSocket: {self.ws_server.error}")
                self.ws_server = None
                return

        self.bridge = Bridge(
            listen_port=listen_port,
            td_host=self.td_host_var.get().strip(),
            td_port=td_port,
            selected_channels=frozenset(self.selected_channels),
            only_racing=self.only_racing_var.get(),
            send_car_name=self.send_car_name_var.get(),
            ws_server=self.ws_server,
            derived=self.derived_var.get(),
            smoothing_settings=smoothing.parse_reglages(self.smoothing_var.get()),
        )
        self.bridge.start()
        # Attente d'un evenement plutot qu'un `time.sleep(0.05)` : ce sommeil
        # figeait l'interface et constituait une course (un bind plus lent que
        # 50 ms etait rapporte comme un demarrage reussi).
        self.bridge.bound.wait(timeout=5)
        if self.bridge.error:
            self.status_var.set(f"Erreur reseau: {self.bridge.error}")
            self.bridge = None
            self._stop_ws()
            return

        self.start_button.configure(text="Arreter")
        self.status_var.set(f"En ecoute sur le port {listen_port}...")

    def _stop_ws(self) -> None:
        if self.ws_server is not None:
            self.ws_server.stop()
            self.ws_server = None

    def _stop_worker(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge.join(timeout=2)
            self.bridge = None
        self._stop_ws()
        self.start_button.configure(text="Demarrer")
        self.status_var.set("Arrete.")

    # -- rafraichissement --------------------------------------------------

    def _refresh_loop(self) -> None:
        if self.bridge is not None:
            # Une mort du thread reseau doit se voir : sans ce controle,
            # l'interface affichait "En ecoute" avec un compteur fige alors
            # que plus rien n'etait emis.
            if not self.bridge.is_alive():
                message = self.bridge.error or "arret inattendu"
                self._stop_worker()
                self.status_var.set(f"Pont interrompu: {message}")
                self.root.after(150, self._refresh_loop)
                return

            values = self.bridge.latest_values
            self._refresh_vehicle_info(values)
            for name, row_id in self.row_by_channel.items():
                if name in values:
                    value = values[name]
                    text = f"{value:.3f}" if isinstance(value, float) else str(value)
                    self.tree.set(row_id, "value", text)
            status = (
                f"En ecoute sur le port {self.bridge.listen_port} | "
                f"paquets recus: {self.bridge.packet_count} | "
                f"canaux transmis: {len(self.selected_channels)}"
            )
            if self.ws_server is not None:
                portee = "reseau" if self.ws_server.host == "0.0.0.0" else "local"
                status += (
                    f" | WebSocket :{self.ws_server.port} ({portee}, "
                    f"{self.ws_server.client_count} client(s))"
                )
            self.status_var.set(status)
        self._refresh_tray()
        self.root.after(150, self._refresh_loop)

    def _refresh_vehicle_info(self, values: dict[str, float]) -> None:
        if not values:
            return
        self.car_name_var.set(car_lookup.describe(values.get("car_ordinal")))
        pi = values.get("car_performance_index")
        cylinders = values.get("num_cylinders")
        self.car_detail_var.set(
            f"classe {car_lookup.car_class_label(values.get('car_class'))}"
            f"  |  PI {int(pi) if pi else '-'}"
            f"  |  {car_lookup.drivetrain_label(values.get('drivetrain_type'))}"
            f"  |  {int(cylinders) if cylinders else '-'} cylindres"
        )

    def _on_close(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge.join(timeout=2)
        self._stop_ws()

        # Les valeurs sont converties avant enregistrement : les ecrire telles
        # quelles remplacait les entiers par defaut de load_config par des
        # chaines, et persistait une saisie invalide ("abc") sans controle.
        def as_number(var: tk.StringVar, fallback, cast=int):
            try:
                return cast(var.get())
            except ValueError:
                return fallback

        self.config_data.update({
            "listen_port": as_number(self.listen_port_var, 5300),
            "td_host": self.td_host_var.get().strip(),
            "td_port": as_number(self.td_port_var, 7000),
            "only_racing": self.only_racing_var.get(),
            "send_car_name": self.send_car_name_var.get(),
            "ws_enabled": self.ws_enabled_var.get(),
            "ws_lan": self.ws_lan_var.get(),
            "derived": self.derived_var.get(),
            "smoothing": self.smoothing_var.get(),
            "ws_differential": self.ws_differential_var.get(),
            "ws_port": as_number(self.ws_port_var, 8765),
            "ws_rate_hz": as_number(self.ws_rate_var, 30.0, float),
            "selected_channels": sorted(self.selected_channels),
        })
        save_config(self.config_data)
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    root.geometry("720x560")
    BridgeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
