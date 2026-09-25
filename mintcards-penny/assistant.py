"""Penny als ein Objekt: verbindet Hirn, Stimme und Dashboard-Ereignisse.

Sprach- und Texteingaben (aus dem Dashboard) laufen beide über respond(),
damit sich nie zwei Antworten überschneiden.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime

log = logging.getLogger("penny")

# Sprachbefehle, die lokal verarbeitet werden, ohne Claude zu fragen.
RESET_COMMANDS = ("neues gespräch", "vergiss alles", "reset")

# Ungefähre Preise in US-Dollar pro 1 Mio. Tokens (Eingabe, Ausgabe) für die Kostenanzeige.
PRICES = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-5": (5.0, 25.0),
}

STATES = ("bereit", "hoert_zu", "versteht", "denkt", "spricht", "fehler")


class EventBus:
    """Einfacher Verteiler für Server-Sent-Events an alle offenen Dashboards."""

    def __init__(self):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:  # hängendes Browserfenster, Ereignis verwerfen
                pass


class Penny:
    def __init__(self, brain, tts=None, events: EventBus | None = None, info: dict | None = None):
        self.brain = brain
        self.tts = tts
        self.events = events or EventBus()
        self.info = info or {}
        self._lock = threading.Lock()
        self.state = "bereit"
        self.turns: list[dict] = self._turns_from_history()
        self.stats = {"turns": 0, "input_tokens": 0, "output_tokens": 0, "kosten_usd": 0.0,
                      "seit": datetime.now().isoformat(timespec="seconds")}

    def _turns_from_history(self) -> list[dict]:
        history = getattr(self.brain, "history", [])
        turns = []
        for i in range(0, len(history) - 1, 2):
            if history[i]["role"] == "user" and history[i + 1]["role"] == "assistant":
                turns.append({"frage": history[i]["content"], "antwort": history[i + 1]["content"],
                              "quelle": "gedaechtnis", "zeit": None, "dauer": {}})
        return turns

    # --- Status ---
    def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.events.publish("status", {"state": state, "detail": detail})

    def snapshot(self) -> dict:
        return {"state": self.state, "turns": self.turns[-50:], "stats": dict(self.stats),
                "info": self.info, "gedaechtnis_turns": len(getattr(self.brain, "history", [])) // 2}

    def _track_usage(self) -> None:
        usage = getattr(self.brain, "last_usage", None)
        if not usage:
            return
        self.stats["input_tokens"] += usage.get("input", 0)
        self.stats["output_tokens"] += usage.get("output", 0)
        price = PRICES.get(self.info.get("modell", ""))
        if price:
            self.stats["kosten_usd"] = round(
                self.stats["input_tokens"] / 1e6 * price[0] + self.stats["output_tokens"] / 1e6 * price[1], 4)

    # --- Kern ---
    def respond(self, text: str, quelle: str = "stimme", speak: bool = True,
                dauer: dict | None = None) -> str:
        """Beantwortet text, spricht die Antwort (optional) und meldet alles ans Dashboard."""
        dauer = dict(dauer or {})
        with self._lock:
            try:
                if text.lower().strip(" .!?") in RESET_COMMANDS:
                    self.brain.reset()
                    self.turns.clear()
                    log.info("Gedächtnis gelöscht.")
                    self.events.publish("gedaechtnis", {"turns": 0})
                    answer = "Erledigt. Wir fangen von vorne an."
                else:
                    self.set_state("denkt")
                    t0 = time.perf_counter()
                    answer = self.brain.ask(text)
                    dauer["claude"] = round(time.perf_counter() - t0, 2)
                    self._track_usage()
                    turn = {"frage": text, "antwort": answer, "quelle": quelle,
                            "zeit": datetime.now().isoformat(timespec="seconds"), "dauer": dauer}
                    self.turns.append(turn)
                    self.stats["turns"] += 1
                    log.info("DU     (%s): %s", quelle, text)
                    log.info("PENNY  (%.1fs Claude): %s", dauer["claude"], answer)
                    self.events.publish("turn", {**turn, "stats": dict(self.stats),
                                                 "gedaechtnis_turns": len(self.brain.history) // 2
                                                 if hasattr(self.brain, "history") else 0})
                if speak and self.tts is not None:
                    self.set_state("spricht")
                    self.tts.speak(answer)
                return answer
            except Exception as exc:
                self.set_state("fehler", str(exc)[:200])
                raise
            finally:
                if self.state != "fehler":
                    self.set_state("bereit")
