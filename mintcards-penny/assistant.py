"""Penny als ein Objekt: verbindet Hirn, Stimme und Dashboard-Ereignisse.

Alle Eingaben laufen über respond(), damit sich nie zwei Antworten überschneiden.
Die Antwort wird gestreamt: Penny spricht den ersten Satz, während Claude noch schreibt.
interrupt() (Barge-in) stoppt die Sprachausgabe sofort.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime

from speech import iter_text

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
    def __init__(self, brain, voice=None, events: EventBus | None = None, info: dict | None = None,
                 streaming: bool = True):
        self.brain = brain
        self.voice = voice  # speech.SpeechOutput oder None (nur Text)
        self.streaming = streaming
        self.events = events or EventBus()
        self.info = info or {}
        self._lock = threading.Lock()
        self._interrupt = threading.Event()
        self._busy = False
        self.state = "bereit"
        self.turns: list[dict] = self._turns_from_history()
        self.stats = {"turns": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                      "cache_write_tokens": 0, "kosten_usd": 0.0,
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
        self.stats["cache_read_tokens"] += usage.get("cache_read", 0)
        self.stats["cache_write_tokens"] += usage.get("cache_write", 0)
        price = PRICES.get(self.info.get("modell", ""))
        if price:
            p_in, p_out = price[0] / 1e6, price[1] / 1e6
            # Cache lesen kostet 10 %, Cache schreiben 125 % des normalen Eingabepreises.
            self.stats["kosten_usd"] = round(
                self.stats["input_tokens"] * p_in + self.stats["output_tokens"] * p_out
                + self.stats["cache_read_tokens"] * p_in * 0.1
                + self.stats["cache_write_tokens"] * p_in * 1.25, 4)

    # --- Unterbrechen (Barge-in) ---
    def interrupt(self) -> None:
        """Stoppt die laufende Sprachausgabe. Darf aus jedem Faden aufgerufen werden."""
        if self._busy and not self._interrupt.is_set():
            log.info("Unterbrochen.")
            self._interrupt.set()

    # --- Sprechen ohne Claude (Begrüßung, Reset-Bestätigung) ---
    def say(self, text: str) -> None:
        with self._lock:
            self._say(text)

    def _say(self, text: str) -> None:
        if self.voice is None:
            return
        self._interrupt.clear()
        self._busy = True
        try:
            self.voice.say(text, self._interrupt, on_audio_start=lambda: self.set_state("spricht"))
        except Exception as exc:
            self.set_state("fehler", str(exc)[:200])
            raise
        finally:
            self._busy = False
            if self.state != "fehler":
                self.set_state("bereit")

    # --- Kern ---
    def respond(self, text: str, quelle: str = "stimme", speak: bool = True,
                dauer: dict | None = None) -> str:
        """Beantwortet text, spricht die Antwort (optional) und meldet alles ans Dashboard."""
        dauer = dict(dauer or {})
        with self._lock:
            if text.lower().strip(" .!?") in RESET_COMMANDS:
                self.brain.reset()
                self.turns.clear()
                log.info("Gedächtnis gelöscht.")
                self.events.publish("gedaechtnis", {"turns": 0})
                answer = "Erledigt. Wir fangen von vorne an."
                if speak:
                    self._say(answer)
                return answer

            self._interrupt.clear()
            self._busy = True
            try:
                self.events.publish("frage", {"text": text})
                self.set_state("denkt")
                t0 = time.perf_counter()
                marks: dict[str, float] = {}

                def on_text(so_far: str) -> None:
                    marks.setdefault("text", time.perf_counter() - t0)
                    self.events.publish("teil", {"text": so_far})

                def on_audio_start() -> None:
                    marks.setdefault("ton", time.perf_counter() - t0)
                    self.set_state("spricht")

                deltas = self.brain.ask_stream(text)
                interrupted = False
                if not (speak and self.voice is not None):
                    answer = "".join(iter_text(deltas, on_text)).strip()
                elif self.streaming:
                    answer, interrupted = self.voice.speak_stream(deltas, self._interrupt, on_text,
                                                                  on_audio_start)
                else:  # STREAMING=nein: erst komplette Antwort, dann sprechen
                    answer = "".join(iter_text(deltas, on_text)).strip()
                    interrupted = not self.voice.say(answer, self._interrupt, on_audio_start)

                dauer["claude"] = round(time.perf_counter() - t0, 2)
                if "text" in marks:
                    dauer["erster_text"] = round(marks["text"], 2)
                if "ton" in marks:
                    dauer["erster_ton"] = round(marks["ton"], 2)
                self._track_usage()
                turn = {"frage": text, "antwort": answer, "quelle": quelle,
                        "zeit": datetime.now().isoformat(timespec="seconds"), "dauer": dauer,
                        "unterbrochen": interrupted}
                self.turns.append(turn)
                self.stats["turns"] += 1
                log.info("DU     (%s): %s", quelle, text)
                if "erster_ton" in dauer:
                    log.info("PENNY  (%.1fs bis zum ersten Ton%s): %s", dauer["erster_ton"],
                             ", unterbrochen" if interrupted else "", answer)
                else:
                    log.info("PENNY  (%.1fs Claude): %s", dauer["claude"], answer)
                self.events.publish("turn", {**turn, "stats": dict(self.stats),
                                             "gedaechtnis_turns": len(self.brain.history) // 2
                                             if hasattr(self.brain, "history") else 0})
                return answer
            except Exception as exc:
                self.set_state("fehler", str(exc)[:200])
                raise
            finally:
                self._busy = False
                if self.state != "fehler":
                    self.set_state("bereit")
