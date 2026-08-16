"""Service de fichiers statiques greffe sur le port du serveur WebSocket.

Permet d'ouvrir l'overlay directement sur `http://<hote>:<port>/` sans avoir
a lancer un second serveur HTTP a cote. Le rappel `process_request` de la
bibliotheque `websockets` est appele pour chaque requete : s'il renvoie une
reponse, la connexion n'est pas promue en WebSocket et sert donc du HTTP
ordinaire ; s'il renvoie None, la negociation WebSocket se poursuit.

Seul le dossier `web/` est expose, en lecture seule.
"""

from __future__ import annotations

from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

WEB_ROOT = (Path(__file__).parent / "web").resolve()
INDEX = "overlay.html"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


def _text_response(status: int, reason: str, message: str) -> Response:
    body = message.encode("utf-8")
    headers = Headers({
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Length": str(len(body)),
        "Connection": "close",
    })
    return Response(status, reason, headers, body)


def _resolve(path: str) -> Path | None:
    """Convertit un chemin d'URL en fichier de `web/`, ou None si interdit."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path in ("", "/"):
        path = "/" + INDEX

    candidate = (WEB_ROOT / path.lstrip("/")).resolve()
    # Barriere anti-remontee : tout ce qui sort de web/ est refuse
    # (`/../config.json`, liens symboliques, chemins absolus...).
    if candidate != WEB_ROOT and WEB_ROOT not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def process_request(connection, request):
    """Sert un fichier statique, ou None pour laisser passer le WebSocket."""
    # Une requete d'upgrade WebSocket doit poursuivre son chemin normal.
    upgrade = request.headers.get("Upgrade", "")
    if upgrade.lower() == "websocket":
        return None

    target = _resolve(request.path)
    if target is None:
        return _text_response(404, "Not Found", "Fichier introuvable.")

    try:
        body = target.read_bytes()
    except OSError:
        return _text_response(500, "Internal Server Error", "Lecture impossible.")

    headers = Headers({
        "Content-Type": _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"),
        "Content-Length": str(len(body)),
        # L'overlay est modifie pendant la mise au point : pas de cache.
        "Cache-Control": "no-store",
        "Connection": "close",
    })
    return Response(200, "OK", headers, body)
