"""Graphical interface for the Forza Horizon telemetry bridge.

Organisation retravaillee : les reglages etaient empiles dans un seul cadre
"Connexion" de sept lignes melangeant reception, OSC, WebSocket et
traitement. Ils sont desormais regroupes par role — Input / OSC output /
WebSocket output — chacun dans son cadre.

Le lissage se reglait en tapant "canal=duree" dans un champ ; il s'applique
maintenant a la selection du tableau, ce qui evite d'avoir a connaitre une
syntaxe et de recopier des noms de canaux a la main.

Lancement: python gui.py
"""

from __future__ import annotations

import json
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import car_lookup
import osc_targets
import smoothing
import tray
from bridge import Bridge
from channel_catalog import CATEGORIES, DEFAULT_SELECTION, UNITS
from ws_server import TelemetryWebSocketServer

CONFIG_PATH = Path(__file__).with_name("config.json")

CHECKED, UNCHECKED = "☑", "☐"


def load_config() -> dict:
    default = {
        "listen_port": 5300,
        "osc_targets": osc_targets.format_target(osc_targets.DEFAULT_TARGET),
        "only_racing": False,
        "send_car_name": True,
        "ws_enabled": True,
        "ws_lan": False,
        "derived": True,
        "ws_differential": True,
        "ws_port": 8765,
        "ws_rate_hz": 60,
        "smoothing": "",
        "tray": True,
        "selected_channels": sorted(DEFAULT_SELECTION),
    }
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # Reprise d'une configuration anterieure, quand la destination OSC
            # etait un couple hote/port unique nomme d'apres TouchDesigner.
            host = saved.pop("td_host", None)
            port = saved.pop("td_port", None)
            if "osc_targets" not in saved and (host or port):
                saved["osc_targets"] = f"{host or '127.0.0.1'}:{port or 7000}"
            default.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def save_config(config: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except OSError:
        pass


class BridgeGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Forza Horizon telemetry bridge")
        self.config_data = load_config()
        self.selected_channels: set[str] = set(self.config_data["selected_channels"])
        self.smoothing_settings: dict[str, float] = smoothing.parse_settings(
            self.config_data["smoothing"])
        self.bridge: Bridge | None = None
        self.ws_server: TelemetryWebSocketServer | None = None
        self.row_by_channel: dict[str, str] = {}
        self.tray: tray.TrayIcon | None = None
        self._current_state: str | None = None
        self._refresh_id: str | None = None

        self._build_settings()
        self._build_vehicle()
        self._build_status()
        self._build_channels()

        self._refresh_smoothing_column()
        self._refresh_controls()
        self._setup_tray()
        # Fermer la fenetre replie dans la barre d'etat plutot que d'arreter
        # le pont : c'est un outil qu'on laisse tourner pendant qu'on joue.
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._refresh_loop()

    # -- layout ------------------------------------------------------------

    def _build_settings(self) -> None:
        """Trois cadres par role, au lieu d'un empilement de sept lignes."""
        outer = ttk.Frame(self.root)
        outer.pack(fill="x", padx=8, pady=(8, 4))
        for column in range(3):
            outer.columnconfigure(column, weight=1, uniform="settings")

        # -- Input
        box = ttk.LabelFrame(outer, text="Input")
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(box, text="Forza UDP port").grid(row=0, column=0, sticky="w",
                                                   padx=6, pady=(6, 2))
        self.listen_port_var = tk.StringVar(value=str(self.config_data["listen_port"]))
        entry = ttk.Entry(box, textvariable=self.listen_port_var, width=8)
        entry.grid(row=0, column=1, sticky="w", padx=6, pady=(6, 2))
        # Change le socket d'ecoute : inapplicable sans redemarrer le pont,
        # donc grise pendant la marche plutot que d'accepter une saisie sans
        # effet.
        self._restart_widgets = [entry]
        self.only_racing_var = tk.BooleanVar(value=self.config_data["only_racing"])
        ttk.Checkbutton(box, text="Only while racing",
                        variable=self.only_racing_var,
                        command=self._on_only_racing_toggled).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6)
        self.derived_var = tk.BooleanVar(value=self.config_data["derived"])
        ttk.Checkbutton(box, text="Computed channels",
                        variable=self.derived_var,
                        command=self._on_derived_toggled).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        # -- OSC output
        box = ttk.LabelFrame(outer, text="OSC output")
        box.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="Destinations (host:port, comma separated)").grid(
            row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        self.osc_targets_var = tk.StringVar(value=self.config_data["osc_targets"])
        entry = ttk.Entry(box, textvariable=self.osc_targets_var)
        entry.grid(row=1, column=0, sticky="we", padx=6)
        self._restart_widgets.append(entry)
        self.send_car_name_var = tk.BooleanVar(value=self.config_data["send_car_name"])
        ttk.Checkbutton(box, text="Send /forza/car_name (a string, not a number)",
                        variable=self.send_car_name_var,
                        command=self._on_send_car_name_toggled).grid(
            row=2, column=0, sticky="w", padx=6, pady=(2, 6))

        # -- WebSocket output
        box = ttk.LabelFrame(outer, text="WebSocket output")
        box.grid(row=0, column=2, sticky="nsew")
        self.ws_enabled_var = tk.BooleanVar(value=self.config_data["ws_enabled"])
        # La case demarre et arrete VRAIMENT le serveur, pont en marche
        # compris : sans cette commande, la cocher pendant la marche ne
        # faisait rien et rien ne le signalait.
        ttk.Checkbutton(box, text="Enabled", variable=self.ws_enabled_var,
                        command=self._on_ws_enabled_toggled).grid(
            row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        ttk.Label(box, text="port").grid(row=0, column=1, sticky="e", padx=2)
        self.ws_port_var = tk.StringVar(value=str(self.config_data["ws_port"]))
        ws_port_entry = ttk.Entry(box, textvariable=self.ws_port_var, width=7)
        ws_port_entry.grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Label(box, text="rate (Hz)").grid(row=1, column=1, sticky="e", padx=2)
        self.ws_rate_var = tk.StringVar(value=str(self.config_data["ws_rate_hz"]))
        ws_rate_entry = ttk.Entry(box, textvariable=self.ws_rate_var, width=7)
        ws_rate_entry.grid(row=1, column=2, sticky="w", padx=(0, 6))
        self.ws_lan_var = tk.BooleanVar(value=self.config_data["ws_lan"])
        ws_lan_box = ttk.Checkbutton(box, text="Open to local network",
                                     variable=self.ws_lan_var)
        ws_lan_box.grid(row=2, column=0, columnspan=3, sticky="w", padx=6)
        self.ws_differential_var = tk.BooleanVar(
            value=self.config_data["ws_differential"])
        ws_diff_box = ttk.Checkbutton(box, text="Differential (changes only)",
                                      variable=self.ws_differential_var)
        ws_diff_box.grid(row=3, column=0, columnspan=3, sticky="w", padx=6)
        # Lues a la construction du serveur : modifiables seulement quand il
        # est arrete. Decocher "Enabled" les rend a nouveau accessibles.
        self._ws_widgets = [ws_port_entry, ws_rate_entry, ws_lan_box, ws_diff_box]
        ttk.Button(box, text="Open overlay", command=self._open_overlay).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))

        # -- Start / stop, sur sa propre ligne pour rester bien visible
        actions = ttk.Frame(self.root)
        actions.pack(fill="x", padx=8)
        self.start_button = ttk.Button(actions, text="Start", width=14,
                                       command=self._toggle_bridge)
        self.start_button.pack(side="left")

    def _build_vehicle(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Vehicle")
        frame.pack(fill="x", padx=8, pady=(6, 0))
        self.car_name_var = tk.StringVar(value="-")
        ttk.Label(frame, textvariable=self.car_name_var,
                  font=("Segoe UI", 11, "bold")).pack(side="left", padx=6, pady=5)
        self.car_detail_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.car_detail_var,
                  foreground="#555").pack(side="left", padx=6)

    def _build_status(self) -> None:
        frame = ttk.Frame(self.root)
        # `side="bottom"` : la barre garde sa place meme si le tableau reclame
        # tout l'espace disponible.
        frame.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        # Pastille identique a celle de la barre d'etat systeme : les deux
        # indicateurs sont pilotes par le meme calcul d'etat.
        try:
            background = ttk.Style().lookup("TFrame", "background") or None
        except tk.TclError:
            background = None
        self.state_canvas = tk.Canvas(frame, width=16, height=16,
                                      highlightthickness=0, borderwidth=0,
                                      **({"bg": background} if background else {}))
        self.state_dot = self.state_canvas.create_oval(3, 3, 14, 14, outline="")
        self.state_canvas.pack(side="left", padx=(2, 6))

        self.state_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.state_var,
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="Stopped.")
        ttk.Label(frame, textvariable=self.status_var,
                  foreground="#555").pack(side="left", padx=(12, 0))
        self._set_state(tray.STOPPED)

    def _build_channels(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Channels")
        frame.pack(fill="both", expand=True, padx=8, pady=6)

        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=6, pady=(6, 4))

        ttk.Label(bar, text="Filter").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(bar, textvariable=self.filter_var, width=18).pack(side="left",
                                                                   padx=(4, 12))

        ttk.Label(bar, text="Send:").pack(side="left")
        for label, action in (("All", self._select_all),
                              ("None", self._select_none),
                              ("Recommended", self._select_recommended),
                              ("Filtered", self._select_filtered)):
            ttk.Button(bar, text=label, width=12, command=action).pack(
                side="left", padx=2)

        # Le lissage s'applique a la selection : plus de syntaxe a connaitre.
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Smoothing (s)").pack(side="left")
        self.smoothing_value_var = tk.StringVar(value="0.15")
        ttk.Entry(bar, textvariable=self.smoothing_value_var, width=6).pack(
            side="left", padx=4)
        ttk.Button(bar, text="Apply to selection", width=18,
                   command=self._smooth_selection).pack(side="left", padx=2)
        ttk.Button(bar, text="Clear", width=8,
                   command=self._clear_selection_smoothing).pack(side="left", padx=2)

        columns = ("send", "channel", "category", "unit", "smoothing", "value")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings",
                                 selectmode="extended")
        for name, text, width, anchor in (
                ("send", "Send", 46, "center"),
                ("channel", "Channel", 230, "w"),
                ("category", "Category", 120, "w"),
                ("unit", "Unit", 210, "w"),
                ("smoothing", "Smoothing", 80, "e"),
                ("value", "Value", 100, "e")):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True, side="left", padx=(6, 0),
                       pady=(0, 6))

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="left", fill="y", pady=(0, 6))
        self.tree.configure(yscrollcommand=scrollbar.set)

        # Bascule uniquement dans la colonne dediee : cliquer le nom d'un
        # canal pour le decocher par accident etait deroutant.
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", lambda _event: self._toggle_selection())

        for category, names in CATEGORIES.items():
            for name in names:
                mark = CHECKED if name in self.selected_channels else UNCHECKED
                row = self.tree.insert("", "end", values=(
                    mark, name, category, UNITS.get(name, ""), "", ""))
                self.row_by_channel[name] = row

    # -- channel selection -------------------------------------------------

    def _apply_filter(self) -> None:
        needle = self.filter_var.get().strip().lower()
        for name, row in self.row_by_channel.items():
            category = self.tree.set(row, "category").lower()
            if needle in name.lower() or needle in category:
                self.tree.reattach(row, "", "end")
            else:
                self.tree.detach(row)

    def _visible_channels(self) -> list[str]:
        return [self.tree.set(row, "channel") for row in self.tree.get_children()]

    def _selected_rows_channels(self) -> list[str]:
        """Canaux surlignes, ou tous les canaux visibles si rien ne l'est."""
        rows = self.tree.selection()
        if rows:
            return [self.tree.set(row, "channel") for row in rows]
        return self._visible_channels()

    def _set_send(self, channels, enabled: bool) -> None:
        for name in channels:
            if enabled:
                self.selected_channels.add(name)
            else:
                self.selected_channels.discard(name)
            self.tree.set(self.row_by_channel[name], "send",
                          CHECKED if enabled else UNCHECKED)
        self._push_selection()

    def _select_all(self) -> None:
        self._set_send(list(self.row_by_channel), True)

    def _select_none(self) -> None:
        self._set_send(list(self.row_by_channel), False)

    def _select_filtered(self) -> None:
        """Coche ce que le filtre laisse voir — le geste courant : filtrer
        "tire", puis tout envoyer."""
        self._set_send(self._visible_channels(), True)

    def _select_recommended(self) -> None:
        self.selected_channels = set(DEFAULT_SELECTION)
        for name, row in self.row_by_channel.items():
            self.tree.set(row, "send",
                          CHECKED if name in self.selected_channels else UNCHECKED)
        self._push_selection()

    def _toggle_selection(self) -> None:
        channels = [self.tree.set(row, "channel") for row in self.tree.selection()]
        if not channels:
            return
        enable = not all(name in self.selected_channels for name in channels)
        self._set_send(channels, enable)

    def _on_click(self, event: tk.Event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return  # hors de la colonne "Send" : on laisse la selection agir
        row = self.tree.identify_row(event.y)
        if not row:
            return
        name = self.tree.set(row, "channel")
        self._set_send([name], name not in self.selected_channels)

    def _push_selection(self) -> None:
        """Transmet la selection au thread reseau.

        On affecte un NOUVEL ensemble fige : le thread en prend un instantane
        a chaque trame. Muter en place l'objet qu'il itere levait
        "Set changed size during iteration" et tuait le thread en silence.
        """
        if self.bridge:
            self.bridge.selected_channels = frozenset(self.selected_channels)

    # -- smoothing ---------------------------------------------------------

    def _smooth_selection(self) -> None:
        try:
            tau = float(self.smoothing_value_var.get())
        except ValueError:
            self.status_var.set("Smoothing: not a number.")
            return
        if tau <= 0:
            self.status_var.set("Smoothing: value must be positive.")
            return

        channels = self._selected_rows_channels()
        refused = [n for n in channels if n in smoothing.NOT_SMOOTHABLE]
        for name in channels:
            if name not in smoothing.NOT_SMOOTHABLE:
                self.smoothing_settings[name] = tau
        self._apply_smoothing()

        applied = len(channels) - len(refused)
        message = f"Smoothing {tau:g} s applied to {applied} channel(s)."
        if refused:
            # Une moyenne entre deux rapports de boite donnerait 2,7.
            message += f" Skipped (not smoothable): {', '.join(refused[:4])}"
            if len(refused) > 4:
                message += f" +{len(refused) - 4}"
        self.status_var.set(message)

    def _clear_selection_smoothing(self) -> None:
        removed = 0
        for name in self._selected_rows_channels():
            if self.smoothing_settings.pop(name, None) is not None:
                removed += 1
        self._apply_smoothing()
        self.status_var.set(f"Smoothing cleared on {removed} channel(s).")

    def _apply_smoothing(self) -> None:
        self._refresh_smoothing_column()
        if self.bridge:
            self.bridge.smoother.configure(self.smoothing_settings)

    def _refresh_smoothing_column(self) -> None:
        for name, row in self.row_by_channel.items():
            tau = self.smoothing_settings.get(name)
            self.tree.set(row, "smoothing", f"{tau:g} s" if tau else "")

    # -- bridge lifecycle --------------------------------------------------

    def _read_port(self, var: tk.StringVar, label: str) -> int | None:
        try:
            value = int(var.get())
        except ValueError:
            self.status_var.set(f"{label}: not a number.")
            return None
        if not (0 < value <= 65535):
            self.status_var.set(f"{label}: out of range (1-65535).")
            return None
        return value

    def _read_osc_targets(self) -> list[tuple[str, int]] | None:
        """L'analyse vit dans osc_targets, partagee avec la ligne de commande :
        les deux copies precedentes avaient deja diverge."""
        try:
            return osc_targets.parse_targets(self.osc_targets_var.get())
        except osc_targets.InvalidTarget as exc:
            self.status_var.set(f"OSC destination: {exc}")
            return None

    def _toggle_bridge(self) -> None:
        if self.bridge is None:
            self._start_bridge()
        else:
            self._stop_bridge()

    def _start_ws(self) -> bool:
        """Demarre le serveur WebSocket avec les reglages affiches.

        Extrait de `_start_bridge` pour que la case "Enabled" puisse s'en
        servir a chaud : la boucle du pont relit `self.ws_server` a chaque
        paquet, donc l'echange est immediat.
        """
        ws_port = self._read_port(self.ws_port_var, "WebSocket port")
        if ws_port is None:
            return False
        try:
            ws_rate = float(self.ws_rate_var.get())
        except ValueError:
            self.status_var.set("WebSocket rate: not a number.")
            return False
        if ws_rate <= 0:
            self.status_var.set("WebSocket rate must be positive.")
            return False
        # Ecoute locale sauf demande explicite : le flux contient la
        # position du vehicule.
        ws_host = "0.0.0.0" if self.ws_lan_var.get() else "127.0.0.1"
        self.ws_server = TelemetryWebSocketServer(
            host=ws_host, port=ws_port, rate_hz=ws_rate,
            differential=self.ws_differential_var.get())
        if not self.ws_server.start():
            self.status_var.set(f"WebSocket error: {self.ws_server.error}")
            self.ws_server = None
            return False
        return True

    def _start_bridge(self) -> None:
        listen_port = self._read_port(self.listen_port_var, "Forza UDP port")
        if listen_port is None:
            return
        targets = self._read_osc_targets()
        if targets is None:
            return

        if self.ws_enabled_var.get() and not self._start_ws():
            return

        try:
            self.bridge = Bridge(
                listen_port=listen_port,
                osc_targets=targets,
                selected_channels=frozenset(self.selected_channels),
                only_racing=self.only_racing_var.get(),
                send_car_name=self.send_car_name_var.get(),
                ws_server=self.ws_server,
                derived=self.derived_var.get(),
                smoothing_settings=self.smoothing_settings,
            )
        except Exception as exc:  # noqa: BLE001 - remonte a la barre d'etat
            # Sans cette garde, une erreur ici laissait le serveur WebSocket
            # demarre juste avant tourner sans reference, port compris.
            self.status_var.set(f"Cannot start: {exc}")
            self.bridge = None
            self._stop_ws()
            return

        self.bridge.start()
        # Attente d'un evenement plutot qu'un `time.sleep` : ce sommeil
        # figeait l'interface et constituait une course.
        self.bridge.bound.wait(timeout=8)
        if self.bridge.error:
            self.status_var.set(f"Network error: {self.bridge.error}")
            self.bridge = None
            self._stop_ws()
            return

        self.start_button.configure(text="Stop")
        self.status_var.set("")
        self._refresh_controls()

    def _stop_ws(self) -> None:
        if self.ws_server is not None:
            self.ws_server.stop()
            self.ws_server = None

    def _stop_bridge(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge.join(timeout=2)
            self.bridge = None
        self._stop_ws()
        self.start_button.configure(text="Start")
        self.status_var.set("Stopped.")
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        """Grise ce qui ne peut pas s'appliquer dans l'etat courant.

        Une commande active qui ne fait rien est un mensonge de l'interface :
        c'etait le cas de tout le cadre WebSocket, pont en marche.
        """
        running = self.bridge is not None
        for widget in self._restart_widgets:
            widget.configure(state="disabled" if running else "normal")
        ws_running = self.ws_server is not None
        for widget in self._ws_widgets:
            widget.configure(state="disabled" if ws_running else "normal")

    # -- reglages appliques a chaud -----------------------------------------

    def _on_ws_enabled_toggled(self) -> None:
        """Demarre ou arrete le serveur sans toucher au pont."""
        wanted = self.ws_enabled_var.get()
        if self.bridge is None:            # pont arrete : rien a demarrer
            self._refresh_controls()
            return
        if wanted and self.ws_server is None:
            if not self._start_ws():
                # Message deja pose par _start_ws ; la case doit refleter
                # l'echec, sinon elle annonce un serveur qui n'existe pas.
                self.ws_enabled_var.set(False)
                self._refresh_controls()
                return
            self.bridge.ws_server = self.ws_server
            self.status_var.set(
                f"WebSocket started on port {self.ws_server.port}.")
        elif not wanted and self.ws_server is not None:
            self.bridge.ws_server = None   # avant l'arret : la boucle le relit
            self._stop_ws()
            self.status_var.set("WebSocket stopped.")
        self._refresh_controls()

    def _on_only_racing_toggled(self) -> None:
        if self.bridge:
            self.bridge.only_racing = self.only_racing_var.get()

    def _on_derived_toggled(self) -> None:
        if self.bridge:
            self.bridge.derived = self.derived_var.get()

    # -- tray --------------------------------------------------------------

    def _setup_tray(self) -> None:
        if not self.config_data.get("tray", True):
            return
        self.tray = tray.TrayIcon(
            on_show=lambda: self.root.after(0, self._show_window),
            on_start_stop=lambda: self.root.after(0, self._toggle_bridge),
            on_open_overlay=lambda: self.root.after(0, self._open_overlay),
            on_quit=lambda: self.root.after(0, self._quit),
        )
        if not self.tray.start():
            self.tray = None  # dependance absente : fenetre ordinaire

    def _hide_to_tray(self) -> None:
        if self.tray is None:
            self._quit()
            return
        self.root.withdraw()

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def _open_overlay(self) -> None:
        port = self.ws_port_var.get().strip() or "8765"
        webbrowser.open(f"http://localhost:{port}/")

    def _quit(self) -> None:
        self._on_close()

    # -- refresh -----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        red, green, blue = tray.COLOURS.get(state, tray.COLOURS[tray.STOPPED])
        self.state_canvas.itemconfigure(self.state_dot,
                                        fill=f"#{red:02x}{green:02x}{blue:02x}")
        self.state_var.set(tray.LABELS.get(state, state))
        self._current_state = state

    def _refresh_state(self) -> None:
        """Un seul calcul d'etat alimente la fenetre et la barre systeme."""
        speed = 0.0
        if self.bridge is not None:
            speed = self.bridge.latest_values.get("speed", 0.0) or 0.0
        state = tray.bridge_state(self.bridge, moving=speed > 0.5)
        if state != self._current_state:
            self._set_state(state)
        if self.tray is not None:
            self.tray.update(state, self.bridge)

    def _refresh_loop(self) -> None:
        if self.bridge is not None:
            # Une mort du thread reseau doit se voir : sans ce controle,
            # l'interface affichait un compteur fige.
            if not self.bridge.is_alive():
                message = self.bridge.error or "unexpected stop"
                self._stop_bridge()
                self.status_var.set(f"Bridge interrupted: {message}")
            else:
                values = self.bridge.latest_values
                self._refresh_vehicle(values)
                for name, row in self.row_by_channel.items():
                    if name in values:
                        value = values[name]
                        self.tree.set(row, "value",
                                      f"{value:.3f}" if isinstance(value, float)
                                      else str(value))
                self.status_var.set(self._running_status())
        self._refresh_state()
        self._refresh_id = self.root.after(150, self._refresh_loop)

    def _running_status(self) -> str:
        bridge = self.bridge
        parts = [f"{bridge.packet_count} packets",
                 f"{len(self.selected_channels)} channels",
                 f"OSC {osc_targets.format_targets(bridge.osc_targets)}"]
        if self.ws_server is not None:
            scope = "LAN" if self.ws_server.host == "0.0.0.0" else "local"
            parts.append(f"WS :{self.ws_server.port} ({scope}, "
                         f"{self.ws_server.client_count} client(s))")
        # Les destinations en echec doivent se voir : une seule cible
        # injoignable n'arrete plus le pont, rien d'autre ne le signalerait.
        if bridge.osc_failures:
            parts.append("FAILED: " + ", ".join(
                osc_targets.format_target(t) for t in bridge.osc_failures))
        return "  |  ".join(parts)

    def _refresh_vehicle(self, values: dict) -> None:
        if not values:
            return
        # Le pont a deja calcule ce libelle une fois au changement de
        # vehicule ; describe() prend un verrou et peut ecrire sur disque.
        self.car_name_var.set(self.bridge.car_name if self.bridge else "-")
        pi = values.get("car_performance_index")
        cylinders = values.get("num_cylinders")
        self.car_detail_var.set(
            f"class {car_lookup.car_class_label(values.get('car_class'))}"
            f"   |   PI {int(pi) if pi else '-'}"
            f"   |   {car_lookup.drivetrain_label(values.get('drivetrain_type'))}"
            f"   |   {int(cylinders) if cylinders else '-'} cylinders")

    # -- shutdown ----------------------------------------------------------

    def _osc_targets_to_save(self) -> str:
        """Repli sur le defaut si la saisie est invalide.

        Sans ce repli, quitter avec un champ vide persistait "" : au
        lancement suivant la cle existait, ecrasait le defaut, et Start
        refusait pour toujours.
        """
        text = self.osc_targets_var.get().strip()
        try:
            osc_targets.parse_targets(text)
            return text
        except osc_targets.InvalidTarget:
            return osc_targets.format_target(osc_targets.DEFAULT_TARGET)

    def _on_close(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge.join(timeout=2)
        self._stop_ws()

        def as_number(var: tk.StringVar, fallback, cast=int):
            try:
                return cast(var.get())
            except ValueError:
                return fallback

        self.config_data.update({
            "listen_port": as_number(self.listen_port_var, 5300),
            "osc_targets": self._osc_targets_to_save(),
            "only_racing": self.only_racing_var.get(),
            "send_car_name": self.send_car_name_var.get(),
            "ws_enabled": self.ws_enabled_var.get(),
            "ws_lan": self.ws_lan_var.get(),
            "ws_differential": self.ws_differential_var.get(),
            "derived": self.derived_var.get(),
            "ws_port": as_number(self.ws_port_var, 8765),
            "ws_rate_hz": as_number(self.ws_rate_var, 60.0, float),
            "smoothing": smoothing.format_settings(self.smoothing_settings),
            "selected_channels": sorted(self.selected_channels),
        })
        save_config(self.config_data)

        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        if self._refresh_id is not None:
            self.root.after_cancel(self._refresh_id)
            self._refresh_id = None
        self.root.destroy()

    def _on_send_car_name_toggled(self) -> None:
        if self.bridge:
            self.bridge.send_car_name = self.send_car_name_var.get()


def size_window(root: tk.Tk, extra_rows: int = 14) -> tuple[int, int]:
    """Dimensionne la fenetre d'apres ce que son contenu demande vraiment.

    Une taille codee en dur avait deja tronque les libelles et pousse la
    barre d'etat hors cadre : elle ne vaut que pour la police et la mise a
    l'echelle de la machine ou elle a ete relevee. On mesure a la place, et
    `minsize` vaut exactement le besoin du contenu — reduire la fenetre ne
    peut donc plus rien cacher.
    """
    root.update_idletasks()
    besoin_l, besoin_h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.minsize(besoin_l, besoin_h)

    # De la place en plus pour le tableau des canaux, qui est la seule zone
    # extensible : sans cela on n'en verrait qu'une poignee de lignes.
    ligne = max(18, tkfont.nametofont("TkDefaultFont").metrics("linespace") + 4)
    largeur = min(besoin_l + 200, root.winfo_screenwidth() - 80)
    hauteur = min(besoin_h + extra_rows * ligne, root.winfo_screenheight() - 120)
    largeur, hauteur = max(largeur, besoin_l), max(hauteur, besoin_h)
    root.geometry(f"{largeur}x{hauteur}")
    return largeur, hauteur


def main() -> None:
    root = tk.Tk()
    BridgeGUI(root)
    size_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
