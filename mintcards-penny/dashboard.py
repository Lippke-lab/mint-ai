"""Lokales Web-Dashboard für Penny (nur Python-Standardbibliothek).

Zeigt Pennys Zustand live: hört zu, versteht, denkt nach, spricht.
Läuft automatisch mit `python main.py` auf http://localhost:8765.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assistant import Penny

log = logging.getLogger(__name__)

PAGE_FILE = Path(__file__).resolve().parent / "dashboard" / "index.html"
PAGE_HEAD = (
    '<!doctype html><html lang="de"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
    "</head><body>"
)
PAGE_TAIL = "</body></html>"


class _Handler(BaseHTTPRequestHandler):
    server_version = "PennyDashboard/1.0"
    dashboard: "Dashboard"  # wird pro Server gesetzt

    # Anfragen nicht ins Terminal loggen, das Penny-Log bleibt lesbar
    def log_message(self, fmt, *args):  # noqa: D401
        log.debug("HTTP " + fmt, *args)

    # --- Sicherheit: nur lokale Aufrufe ---
    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _check_request(self) -> bool:
        if self.headers.get("Host", "") not in self._allowed_hosts():
            self._send_json({"fehler": "Nur lokaler Zugriff erlaubt."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    # --- Antworten ---
    def _send_json(self, data, status=HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --- Routen ---
    def do_GET(self):  # noqa: N802
        if not self._check_request():
            return
        d = self.dashboard
        if self.path in ("/", "/index.html"):
            html = (PAGE_HEAD + PAGE_FILE.read_text(encoding="utf-8") + PAGE_TAIL).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
        elif self.path == "/api/state":
            self._send_json(d.state())
        elif self.path == "/api/events":
            self._stream_events()
        else:
            self._send_json({"fehler": "Nicht gefunden."}, HTTPStatus.NOT_FOUND)

    def _stream_events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.dashboard.penny.events.subscribe()
        try:
            while not self.dashboard.stopping.is_set():
                try:
                    event, data = q.get(timeout=15)
                    payload = json.dumps(data, ensure_ascii=False)
                    self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # hält die Verbindung offen
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Browser-Tab geschlossen
        finally:
            self.dashboard.penny.events.unsubscribe(q)


class Dashboard:
    def __init__(self, penny: Penny, port: int = 8765):
        self.penny = penny
        self.port = port
        self.stopping = threading.Event()
        handler = type("Handler", (_Handler,), {"dashboard": self})
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.server.daemon_threads = True
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def start(self) -> None:
        self._thread.start()
        log.info("Dashboard läuft auf %s", self.url)

    def stop(self) -> None:
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()

    def state(self) -> dict:
        return {"penny": self.penny.snapshot()}


def open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - kein Browser vorhanden ist kein Fehler
        pass
