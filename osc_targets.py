"""Analyse et mise en forme des destinations OSC.

Definition UNIQUE du format "host:port", consommee par la ligne de commande
et par l'interface. Les deux avaient leur propre copie, et elles avaient
diverge des la naissance : l'interface acceptait une liste separee par des
virgules que la ligne de commande refusait, si bien que la chaine enregistree
dans config.json ne pouvait pas etre recopiee en `--osc`.

Meme decoupage que `smoothing.parse_settings` / `format_settings` : une
fonction leve, chaque point d'entree presente l'erreur a sa facon.

Les messages d'erreur sont AFFICHES : ils sont donc en anglais.
"""

from __future__ import annotations

import socket

DEFAULT_TARGET: tuple[str, int] = ("127.0.0.1", 7000)

PORT_MIN, PORT_MAX = 1, 65535


class InvalidTarget(ValueError):
    """Destination inexploitable. Le message est destine a l'utilisateur."""


def parse_target(text: str) -> tuple[str, int]:
    """Analyse une destination "host:port".

    Accepte la forme IPv6 entre crochets (`[::1]:7000`). Une adresse IPv6
    nue est refusee : `rpartition(":")` en tirerait l'hote `::` et le port
    `1`, une destination acceptee en silence vers un port que personne n'a
    demande.
    """
    text = text.strip()
    if not text:
        raise InvalidTarget("empty destination")

    if text.startswith("["):
        closing = text.find("]")
        if closing == -1 or not text[closing + 1:].startswith(":"):
            raise InvalidTarget(
                f"\"{text}\": expected IPv6 form [address]:port")
        host, port_text = text[1:closing], text[closing + 2:]
    else:
        host, separator, port_text = text.rpartition(":")
        if not separator:
            raise InvalidTarget(f"\"{text}\": missing port (expected host:port)")
        if ":" in host:
            # Ne pas suggerer la forme issue du mauvais decoupage : elle est
            # deja fausse, c'est precisement le probleme.
            raise InvalidTarget(
                f"\"{text}\": IPv6 address must be bracketed, "
                f"for example [::1]:7000")

    host = host.strip()
    if not host:
        raise InvalidTarget(
            f"\"{text}\": missing host. An empty host resolves to a local "
            f"interface and sending then fails silently.")

    # `int()` dans un try, et non `isdigit()` : ce dernier est vrai pour des
    # caracteres que `int()` refuse ('²'.isdigit() vaut True), ce qui
    # faisait lever une ValueError nue au lieu d'afficher ce message.
    try:
        port = int(port_text.strip())
    except ValueError:
        raise InvalidTarget(f"\"{text}\": port is not a number") from None
    if not (PORT_MIN <= port <= PORT_MAX):
        raise InvalidTarget(
            f"\"{text}\": port out of range ({PORT_MIN}-{PORT_MAX})")

    return host, port


def parse_targets(text: str) -> list[tuple[str, int]]:
    """Analyse "host:port, host:port". Doublons retires, ordre conserve.

    Deux fois la meme destination ouvrirait deux sockets et doublerait
    reellement le trafic vers le meme point d'arrivee.
    """
    targets: list[tuple[str, int]] = []
    for chunk in text.replace(";", ",").split(","):
        if chunk.strip():
            targets.append(parse_target(chunk))
    if not targets:
        raise InvalidTarget("no OSC destination")
    return list(dict.fromkeys(targets))


def format_target(target: tuple[str, int]) -> str:
    host, port = target
    # Les crochets sont necessaires pour que la chaine puisse etre relue.
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def format_targets(targets) -> str:
    return ", ".join(format_target(target) for target in targets)


def resolve(target: tuple[str, int]) -> tuple[str, int]:
    """Remplace un nom d'hote par son adresse numerique.

    python-osc resout le nom dans son constructeur puis JETTE le resultat :
    il conserve la chaine d'origine et la repasse a `sendto`, ce qui fait
    re-resoudre le nom a CHAQUE datagramme. Mesure : 3,5 us vers une adresse
    numerique contre 167,7 us vers "localhost", soit 48 fois plus — a
    ~5400 messages par seconde, la boucle de reception ne suivrait pas.
    """
    host, port = target
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    return infos[0][4][0], port
