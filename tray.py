"""Icone de barre d'etat systeme pour la passerelle.

C'est un outil qu'on laisse tourner pendant qu'on joue : garder une console
ouverte ou une fenetre au premier plan n'a pas de sens. L'icone donne l'etat
d'un coup d'oeil et permet de fermer la fenetre sans arreter le pont.

L'etat affiche reprend exactement la distinction etablie pour la trame d'etat
WebSocket : des paquets qui arrivent sans rien faire varier (menu, voiture a
l'arret) restent un flux VIVANT, seul un silence prolonge signale un flux
mort. Voir ws_server.note_activity().

Les libelles sont AFFICHES : ils sont donc en anglais.
"""

from __future__ import annotations

import threading

# Etats possibles, du plus grave au plus sain.
STOPPED = "stopped"
FAILED = "failed"
NO_DATA = "no_data"
IDLE = "idle"
ACTIVE = "active"

COLOURS = {
    STOPPED: (110, 110, 110),    # gris   : pont a l'arret
    FAILED: (220, 60, 60),       # rouge  : le pont s'est interrompu
    NO_DATA: (240, 170, 40),     # orange : aucun paquet ne vient du jeu
    IDLE: (240, 210, 60),        # jaune  : paquets recus, mais rien ne bouge
    ACTIVE: (70, 200, 90),       # vert   : telemetrie en mouvement
}

LABELS = {
    STOPPED: "Bridge stopped",
    FAILED: "Bridge interrupted",
    NO_DATA: "No packets from the game",
    IDLE: "Game connected, vehicle stationary",
    ACTIVE: "Telemetry active",
}


def bridge_state(bridge, moving: bool | None = None) -> str:
    """Deduit l'etat a afficher a partir du pont.

    `moving` permet de distinguer le jaune du vert ; None revient a ne pas
    faire la distinction (on considere le flux actif).
    """
    if bridge is None:
        return STOPPED
    if bridge.error:
        return FAILED
    if not bridge.is_alive():
        return FAILED
    # `received_count` compte les paquets du jeu avant tout filtrage :
    # avec "seulement en course", `packet_count` reste a 0 en menu alors que
    # le jeu emet, et l'etat annonce etait NO_DATA. Repli sur `packet_count`
    # pour les objets qui n'exposent pas le compteur detaille.
    recus = getattr(bridge, "received_count", None)
    if recus is None:
        recus = getattr(bridge, "packet_count", 0)
    if recus == 0:
        return NO_DATA
    if moving is False:
        return IDLE
    return ACTIVE


def tooltip(state: str, bridge=None) -> str:
    text = LABELS.get(state, state)
    # Meme compteur que l'etat : sans cela l'infobulle annonce 0 paquet
    # pendant que la pastille dit que le jeu est connecte.
    recus = getattr(bridge, "received_count", None)
    if recus is None:
        recus = getattr(bridge, "packet_count", 0)
    if bridge is not None and recus:
        text += f" — {recus} packets"
    return text


def icon_image(state: str, size: int = 64):
    """Pastille pleine de la couleur de l'etat.

    Import de Pillow differe : le module doit rester importable pour les
    tests de logique meme sans dependance graphique.
    """
    from PIL import Image, ImageDraw

    colour = COLOURS.get(state, COLOURS[STOPPED])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=colour + (255,))
    return image


class TrayIcon:
    """Icone systeme pilotee depuis l'interface graphique.

    pystray tourne dans son propre thread ; toute action de menu doit donc
    repasser par la boucle tkinter (`root.after`) avant de toucher a
    l'interface.
    """

    def __init__(self, on_show, on_start_stop, on_open_overlay, on_quit):
        self._on_show = on_show
        self._on_start_stop = on_start_stop
        self._on_open_overlay = on_open_overlay
        self._on_quit = on_quit
        self._icon = None
        self._state = STOPPED
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            return False
        return True

    def start(self) -> bool:
        if not self.available:
            return False
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Show window", lambda: self._on_show(), default=True),
            pystray.MenuItem("Start / stop", lambda: self._on_start_stop()),
            pystray.MenuItem("Open overlay", lambda: self._on_open_overlay()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self._on_quit()),
        )
        self._icon = pystray.Icon("forza_bridge", icon_image(self._state),
                                  tooltip(self._state), menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        return True

    def update(self, state: str, bridge=None) -> None:
        """Change la pastille si l'etat a change (repeindre a chaque trame
        ferait clignoter l'icone inutilement)."""
        if self._icon is None:
            return
        if state != self._state:
            self._state = state
            self._icon.icon = icon_image(state)
        self._icon.title = tooltip(state, bridge)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
