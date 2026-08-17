"""Analyse et mise en forme des destinations OSC.

Definition UNIQUE du format "hote:port", consommee par la ligne de commande
et par l'interface. Les deux avaient leur propre copie, et elles avaient
diverge des la naissance : l'interface acceptait une liste separee par des
virgules que la ligne de commande refusait, si bien que la chaine enregistree
dans config.json ne pouvait pas etre recopiee en `--osc`.

Meme decoupage que `smoothing.parse_reglages` / `formate_reglages` : une
fonction leve, chaque point d'entree presente l'erreur a sa facon.
"""

from __future__ import annotations

import socket

CIBLE_PAR_DEFAUT: tuple[str, int] = ("127.0.0.1", 7000)

PORT_MIN, PORT_MAX = 1, 65535


class CibleInvalide(ValueError):
    """Destination inexploitable. Le message est destine a l'utilisateur."""


def parse_cible(texte: str) -> tuple[str, int]:
    """Analyse une destination "hote:port".

    Accepte la forme IPv6 entre crochets (`[::1]:7000`). Une adresse IPv6
    nue est refusee : `rpartition(":")` en tirerait l'hote `::` et le port
    `1`, une destination acceptee en silence vers un port que personne n'a
    demande.
    """
    texte = texte.strip()
    if not texte:
        raise CibleInvalide("destination vide")

    if texte.startswith("["):
        fermeture = texte.find("]")
        if fermeture == -1 or not texte[fermeture + 1:].startswith(":"):
            raise CibleInvalide(
                f"\"{texte}\" : forme IPv6 attendue [adresse]:port")
        hote, port_texte = texte[1:fermeture], texte[fermeture + 2:]
    else:
        hote, separateur, port_texte = texte.rpartition(":")
        if not separateur:
            raise CibleInvalide(f"\"{texte}\" : port manquant (attendu hote:port)")
        if ":" in hote:
            # Ne pas tenter de reconstruire la suggestion depuis le decoupage :
            # il est deja faux, c'est precisement le probleme.
            raise CibleInvalide(
                f"\"{texte}\" : adresse IPv6 a mettre entre crochets, "
                f"par exemple [::1]:7000")

    hote = hote.strip()
    if not hote:
        raise CibleInvalide(
            f"\"{texte}\" : hote manquant. Un hote vide est resolu vers une "
            f"interface locale et l'envoi echoue ensuite silencieusement.")

    # `int()` dans un try, et non `isdigit()` : ce dernier est vrai pour des
    # caracteres que `int()` refuse ('²'.isdigit() vaut True), ce qui
    # faisait lever une ValueError nue au lieu d'afficher ce message.
    try:
        port = int(port_texte.strip())
    except ValueError:
        raise CibleInvalide(f"\"{texte}\" : port non numerique") from None
    if not (PORT_MIN <= port <= PORT_MAX):
        raise CibleInvalide(
            f"\"{texte}\" : port hors plage ({PORT_MIN}-{PORT_MAX})")

    return hote, port


def parse_cibles(texte: str) -> list[tuple[str, int]]:
    """Analyse "hote:port, hote:port". Doublons retires, ordre conserve.

    Deux fois la meme destination ouvrirait deux sockets et doublerait
    reellement le trafic vers le meme point d'arrivee.
    """
    cibles: list[tuple[str, int]] = []
    for morceau in texte.replace(";", ",").split(","):
        if morceau.strip():
            cibles.append(parse_cible(morceau))
    if not cibles:
        raise CibleInvalide("aucune destination OSC")
    return list(dict.fromkeys(cibles))


def formate_cible(cible: tuple[str, int]) -> str:
    hote, port = cible
    # Les crochets sont necessaires pour que la chaine puisse etre relue.
    return f"[{hote}]:{port}" if ":" in hote else f"{hote}:{port}"


def formate_cibles(cibles) -> str:
    return ", ".join(formate_cible(cible) for cible in cibles)


def resout(cible: tuple[str, int]) -> tuple[str, int]:
    """Remplace un nom d'hote par son adresse numerique.

    python-osc resout le nom dans son constructeur puis JETTE le resultat :
    il conserve la chaine d'origine et la repasse a `sendto`, ce qui fait
    re-resoudre le nom a CHAQUE datagramme. Mesure : 3,5 us vers une adresse
    numerique contre 167,7 us vers "localhost", soit 48 fois plus — a
    ~5400 messages par seconde, la boucle de reception ne suivrait pas.
    """
    hote, port = cible
    infos = socket.getaddrinfo(hote, port, type=socket.SOCK_DGRAM)
    return infos[0][4][0], port
