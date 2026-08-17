"""Icone de barre d'etat systeme pour la passerelle.

C'est un outil qu'on laisse tourner pendant qu'on joue : garder une console
ouverte ou une fenetre au premier plan n'a pas de sens. L'icone donne l'etat
d'un coup d'oeil et permet de fermer la fenetre sans arreter le pont.

L'etat affiche reprend exactement la distinction etablie pour la trame d'etat
WebSocket : des paquets qui arrivent sans rien faire varier (menu, voiture a
l'arret) restent un flux VIVANT, seul un silence prolonge signale un flux
mort. Voir ws_server.note_activity().
"""

from __future__ import annotations

import threading

# Etats possibles, du plus grave au plus sain.
ARRETE = "arrete"
ERREUR = "erreur"
SANS_FLUX = "sans_flux"
EN_ATTENTE = "en_attente"
ACTIF = "actif"

COULEURS = {
    ARRETE: (110, 110, 110),      # gris  : pont a l'arret
    ERREUR: (220, 60, 60),        # rouge : le pont s'est interrompu
    SANS_FLUX: (240, 170, 40),    # orange: aucun paquet ne vient du jeu
    EN_ATTENTE: (240, 210, 60),   # jaune : paquets recus, mais rien ne bouge
    ACTIF: (70, 200, 90),         # vert  : telemetrie en mouvement
}

LIBELLES = {
    ARRETE: "Passerelle arretee",
    ERREUR: "Passerelle interrompue",
    SANS_FLUX: "Aucun paquet recu du jeu",
    EN_ATTENTE: "Jeu connecte, vehicule a l'arret",
    ACTIF: "Telemetrie active",
}


def etat_pont(bridge, en_mouvement: bool | None = None) -> str:
    """Deduit l'etat a afficher a partir du pont.

    `en_mouvement` permet de distinguer le jaune du vert ; None revient a ne
    pas faire la distinction (on considere le flux actif).
    """
    if bridge is None:
        return ARRETE
    if bridge.error:
        return ERREUR
    if not bridge.is_alive():
        return ERREUR
    if bridge.packet_count == 0:
        return SANS_FLUX
    if en_mouvement is False:
        return EN_ATTENTE
    return ACTIF


def infobulle(etat: str, bridge=None) -> str:
    texte = LIBELLES.get(etat, etat)
    if bridge is not None and getattr(bridge, "packet_count", 0):
        texte += f" — {bridge.packet_count} paquets"
    return texte


def image_icone(etat: str, taille: int = 64):
    """Pastille pleine de la couleur de l'etat.

    Import de Pillow differe : le module doit rester importable pour les
    tests de logique meme sans dependance graphique.
    """
    from PIL import Image, ImageDraw

    couleur = COULEURS.get(etat, COULEURS[ARRETE])
    image = Image.new("RGBA", (taille, taille), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(image)
    marge = taille // 8
    dessin.ellipse([marge, marge, taille - marge, taille - marge],
                   fill=couleur + (255,))
    return image


class TrayIcon:
    """Icone systeme pilotee depuis l'interface graphique.

    pystray tourne dans son propre thread ; toute action de menu doit donc
    repasser par la boucle tkinter (`root.after`) avant de toucher a l'interface.
    """

    def __init__(self, on_show, on_start_stop, on_open_overlay, on_quit):
        self._on_show = on_show
        self._on_start_stop = on_start_stop
        self._on_open_overlay = on_open_overlay
        self._on_quit = on_quit
        self._icon = None
        self._etat = ARRETE
        self._thread: threading.Thread | None = None

    @property
    def disponible(self) -> bool:
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            return False
        return True

    def start(self) -> bool:
        if not self.disponible:
            return False
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Afficher la fenetre", lambda: self._on_show(), default=True),
            pystray.MenuItem("Demarrer / arreter", lambda: self._on_start_stop()),
            pystray.MenuItem("Ouvrir l'overlay", lambda: self._on_open_overlay()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda: self._on_quit()),
        )
        self._icon = pystray.Icon("forza_bridge", image_icone(self._etat),
                                  infobulle(self._etat), menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        return True

    def update(self, etat: str, bridge=None) -> None:
        """Change la pastille si l'etat a change (repeindre a chaque trame
        ferait clignoter l'icone inutilement)."""
        if self._icon is None:
            return
        if etat != self._etat:
            self._etat = etat
            self._icon.icon = image_icone(etat)
        self._icon.title = infobulle(etat, bridge)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
