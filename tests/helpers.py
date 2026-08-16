"""Utilitaires partages par les tests."""

from __future__ import annotations

import socket
import struct
import time

from forza_telemetry import HORIZON_DASH_SIZE, _HORIZON_DASH

# Offsets des champs dans le paquet, pour fabriquer des trames de test.
OFFSETS: dict[str, tuple[int, str]] = {}
_off = 0
for _name, _type in _HORIZON_DASH:
    OFFSETS[_name] = (_off, _type)
    _off += struct.calcsize(_type)


def make_packet(size: int = HORIZON_DASH_SIZE + 1, **values) -> bytes:
    """Fabrique un paquet Forza synthetique (324 o par defaut, comme FH6)."""
    buffer = bytearray(size)
    struct.pack_into("<i", buffer, 0, int(values.pop("is_race_on", 1)))
    for name, value in values.items():
        offset, fmt = OFFSETS[name]
        struct.pack_into("<" + fmt, buffer, offset, value)
    return bytes(buffer)


def free_port(kind: int = socket.SOCK_DGRAM) -> int:
    """Un port libre sur la boucle locale."""
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Attend qu'une condition devienne vraie. Evite les sommeils fixes,
    sources de tests instables sur une machine chargee."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class OscRecorder:
    """Remplace le client OSC pour capturer ce qui est reellement emis."""

    def __init__(self):
        self.messages: list[tuple[str, object]] = []

    def send_message(self, address, value):
        self.messages.append((address, value))

    @property
    def addresses(self) -> set[str]:
        return {address for address, _ in self.messages}
