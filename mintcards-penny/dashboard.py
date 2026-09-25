"""Lokales Web-Dashboard für Penny und MintCards (nur Python-Standardbibliothek).

Läuft automatisch mit `python main.py` auf http://localhost:8765.
Allein starten (ohne Mikrofon, nur Text-Chat):  python dashboard.py [--ohne-claude]
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assistant import Penny
from mintcards_data import MintCardsData

log = logging.getLogger(__name__)

PAGE_FILE = Path(__file__).resolve().parent / "dashboard" / "index.html"
PAGE_HEAD = (
    '<!doctype html><html lang="de"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
    "</head><body>"
)
PAGE_TAIL = "</body></html>"
MAX_BODY = 64 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "PennyDashboard/1.0"
    dashboard: "Dashboard"  # wird pro Server gesetzt

    # Anfragen nicht ins Terminal loggen, das Penny-Log bleibt lesbar
    def log_message(self, fmt, *args):  # noqa: D401
        log.debug("HTTP " + fmt, *args)

    # --- Sicherheit: nur lokale Aufrufe, keine fremden Webseiten ---
    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _check_request(self, write: bool) -> bool:
        if self.headers.get("Host", "") not in self._allowed_hosts():
            self._send_json({"fehler": "Nur lokaler Zugriff erlaubt."}, HTTPStatus.FORBIDDEN)
            return False
        if write:
            origin = self.headers.get("Origin")
            if origin and origin.removeprefix("http://") not in self._allowed_hosts():
                self._send_json({"fehler": "Fremde Herkunft blockiert."}, HTTPStatus.FORBIDDEN)
                return False
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._send_json({"fehler": "JSON erwartet."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
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

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Anfrage zu groß.")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON-Objekt erwartet.")
        return data

    # --- Routen ---
    def do_GET(self):  # noqa: N802
        if not self._check_request(write=False):
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

    def do_POST(self):  # noqa: N802
        self._write("POST")

    def do_DELETE(self):  # noqa: N802
        self._write("DELETE")

    def _write(self, method: str) -> None:
        if not self._check_request(write=True):
            return
        d = self.dashboard
        path = self.path
        try:
            body = self._read_json()
            if method == "POST" and path == "/api/ask":
                self._send_json(d.ask(body.get("text", ""), bool(body.get("sprechen", True))))
            elif method == "POST" and path == "/api/einkaufsliste":
                self._send_json(d.changed(d.data.add_einkauf(body.get("text"), body.get("maxpreis"))))
            elif method == "POST" and (m := re.fullmatch(r"/api/einkaufsliste/(\w+)/toggle", path)):
                self._send_json(d.changed(d.data.toggle_einkauf(m[1])))
            elif method == "DELETE" and (m := re.fullmatch(r"/api/einkaufsliste/(\w+)", path)):
                d.data.einkaufsliste.remove(m[1])
                self._send_json(d.changed({"ok": True}))
            elif method == "POST" and path == "/api/bestand":
                self._send_json(d.changed(d.data.add_karte(body)))
            elif method == "DELETE" and (m := re.fullmatch(r"/api/bestand/(\w+)", path)):
                d.data.bestand.remove(m[1])
                self._send_json(d.changed({"ok": True}))
            else:
                self._send_json({"fehler": "Nicht gefunden."}, HTTPStatus.NOT_FOUND)
        except KeyError:
            self._send_json({"fehler": "Eintrag nicht gefunden."}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"fehler": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            log.error("Dashboard-Fehler: %s", exc)
            self._send_json({"fehler": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
    def __init__(self, penny: Penny, data: MintCardsData, port: int = 8765):
        self.penny = penny
        self.data = data
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
        return {"penny": self.penny.snapshot(), "mintcards": self.data.snapshot()}

    def changed(self, result):
        self.penny.events.publish("mintcards", self.data.snapshot())
        return result

    def ask(self, text: str, sprechen: bool) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("Bitte eine Frage eingeben.")
        answer = self.penny.respond(text[:2000], quelle="dashboard", speak=sprechen)
        return {"antwort": answer}


def open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - kein Browser vorhanden ist kein Fehler
        pass


if __name__ == "__main__":
    # Dashboard allein starten: Text-Chat mit Penny, ohne Mikrofon und ohne Sprachausgabe.
    import sys

    from claude_brain import ClaudeBrain, EchoBrain, Memory
    from config import SYSTEM_PROMPT_FILE, load_config_or_exit

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    echo = "--ohne-claude" in sys.argv
    cfg = load_config_or_exit(require_keys=() if echo else ("ANTHROPIC_API_KEY",))
    brain = EchoBrain() if echo else ClaudeBrain(
        cfg.anthropic_api_key, cfg.claude_model, SYSTEM_PROMPT_FILE, cfg.history_turns,
        cfg.claude_effort, Memory(cfg.memory_file))
    penny = Penny(brain, tts=None, info={
        "modell": "echo (ohne Claude)" if echo else cfg.claude_model,
        "stimme": "aus (nur Text)", "stt": "aus", "taste": "–", "modus": "nur Dashboard",
        "gedaechtnis_max": cfg.history_turns})
    dash = Dashboard(penny, MintCardsData(cfg.data_dir), cfg.dashboard_port)
    dash.start()
    if cfg.dashboard_open:
        open_browser(dash.url)
    print(f"\nDashboard: {dash.url}   (Ctrl+C beendet)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        dash.stop()
        print("\nDashboard beendet.")
