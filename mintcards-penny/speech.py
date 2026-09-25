"""Satzweise Sprachausgabe: Penny fängt an zu sprechen, während Claude noch schreibt.

Ablauf pro Antwort (drei Fäden, damit zwischen den Sätzen keine Pausen entstehen):

    Claude-Text  ──>  Sätze  ──>  ElevenLabs (Audio-Stream)  ──>  Lautsprecher
    (Hauptfaden)      Queue       Abruf-Faden                     Wiedergabe-Faden

Der Abruf-Faden holt schon den nächsten Satz, während der vorige noch läuft.
Ein gesetztes stop-Event (Barge-in) bricht Abruf und Wiedergabe sofort ab.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator

log = logging.getLogger(__name__)

# Abkürzungen, nach deren Punkt kein Satz endet ("z. B.", "ca. 40 Euro", ...)
ABBREVIATIONS = frozenset({
    "z", "b", "d", "h", "u", "a", "o", "s", "ca", "bzw", "nr", "usw", "evtl", "ggf", "inkl",
    "zzgl", "exkl", "st", "dr", "vs", "mio", "mrd", "tsd", "min", "max", "bspw", "vgl", "ggü",
})

# Satzende: . ! ? oder …, optional gefolgt von Anführungszeichen/Klammer, danach Leerraum.
_BOUNDARY = re.compile(r"[.!?…]+[\"'“”»«)\]]*(?=\s)|\n+")
_WORD_BEFORE = re.compile(r"(\w+)[.]$")

MIN_SENTENCE_CHARS = 12  # sehr kurze Stücke ("Klar.") an den nächsten Satz hängen

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]+"
)


def clean_for_speech(text: str) -> str:
    """Entfernt alles, was vorgelesen komisch klingt (Markdown, Emojis, Gedankenstriche)."""
    text = _EMOJI.sub("", text)
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text, flags=re.MULTILINE)  # Aufzählungen
    text = re.sub(r"[*_#`>|]+", "", text)  # Markdown-Zeichen
    text = re.sub(r"\s+[–—]\s+", ", ", text)  # Gedankenstrich = kurze Pause
    text = re.sub(r"(\d)\s*€", r"\1 Euro", text)
    text = text.replace("€", "Euro").replace("%", " Prozent").replace("&", " und ")
    return re.sub(r"\s+", " ", text).strip()


class SentenceSplitter:
    """Sammelt Text-Häppchen und gibt fertige Sätze zurück, sobald sie komplett sind."""

    def __init__(self, min_chars: int = MIN_SENTENCE_CHARS):
        self.min_chars = min_chars
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        pos = 0
        while True:
            cut = self._next_cut(pos)
            if cut is None:
                break
            sentence = self._buf[:cut].strip()
            self._buf = self._buf[cut:].lstrip()
            pos = 0
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []

    def _next_cut(self, start: int) -> int | None:
        for m in _BOUNDARY.finditer(self._buf, start):
            end = m.end()
            if len(self._buf[:end].strip()) < self.min_chars:
                continue
            if m.group().startswith(".") and not m.group().startswith(".."):
                word = _WORD_BEFORE.search(self._buf[: m.start() + 1])
                if word and (word.group(1).lower() in ABBREVIATIONS or word.group(1).isdigit()):
                    continue  # "z. B." oder "am 3. Mai" beendet keinen Satz
            return end
        return None


class BufferPlayer:
    """Ersatz-Lautsprecher: sammelt PCM im Speicher (Smoke-Test, Unit-Tests)."""

    def __init__(self):
        self.data = bytearray()
        self.aborted = False

    def write(self, pcm: bytes) -> None:
        self.data += pcm

    def finish(self) -> None:
        pass

    def abort(self) -> None:
        self.aborted = True


_END = object()  # Ende-Markierung in den Queues


class SpeechOutput:
    """Verbindet TTS und Lautsprecher und spricht Text, auch während er noch entsteht."""

    def __init__(self, tts, player_factory: Callable[[], object] | None = None):
        self.tts = tts
        self._player_factory = player_factory or self._default_player

    def _default_player(self):
        from audio_output import PcmPlayer  # erst hier: sounddevice braucht PortAudio
        from tts_elevenlabs import PCM_RATE

        return PcmPlayer(PCM_RATE)

    def say(self, text: str, stop: threading.Event | None = None,
            on_audio_start: Callable[[], None] | None = None) -> bool:
        """Spricht einen fertigen Text. Gibt False zurück, wenn unterbrochen wurde."""
        _, interrupted = self.speak_stream([text], stop, on_audio_start=on_audio_start)
        return not interrupted

    def speak_stream(self, deltas: Iterable[str], stop: threading.Event | None = None,
                     on_text: Callable[[str], None] | None = None,
                     on_audio_start: Callable[[], None] | None = None) -> tuple[str, bool]:
        """Spricht Text-Häppchen satzweise, sobald ein Satz komplett ist.

        Gibt (kompletter Text, unterbrochen?) zurück. Der Text wird immer vollständig
        gelesen, auch nach einer Unterbrechung, damit Pennys Gedächtnis stimmt.
        Fehler aus TTS oder Wiedergabe werden am Ende im Aufrufer-Faden erneut ausgelöst.
        """
        stop = stop or threading.Event()
        sentences: queue.Queue = queue.Queue()
        audio: queue.Queue = queue.Queue(maxsize=256)
        errors: list[BaseException] = []

        fetcher = threading.Thread(target=self._fetch, args=(sentences, audio, stop, errors),
                                   name="penny-tts", daemon=True)
        player = threading.Thread(target=self._play, args=(audio, stop, errors, on_audio_start),
                                  name="penny-audio", daemon=True)
        fetcher.start()
        player.start()

        splitter = SentenceSplitter()
        parts: list[str] = []
        try:
            for delta in deltas:
                parts.append(delta)
                if on_text:
                    on_text("".join(parts))
                for sentence in splitter.feed(delta):
                    sentences.put(sentence)
            for sentence in splitter.flush():
                sentences.put(sentence)
        except BaseException:
            stop.set()  # z. B. Claude-Fehler: Ausgabe sofort beenden
            raise
        finally:
            sentences.put(_END)
            try:
                fetcher.join()
                player.join()
            except BaseException:  # Ctrl+C während Penny spricht
                stop.set()
                raise

        if errors:
            raise errors[0]
        return "".join(parts).strip(), stop.is_set()

    # --- Faden 1: Sätze in Audio umwandeln ---
    def _fetch(self, sentences: queue.Queue, audio: queue.Queue, stop: threading.Event,
               errors: list) -> None:
        spoken = ""
        try:
            while True:
                sentence = sentences.get()
                if sentence is _END or stop.is_set():
                    break
                text = clean_for_speech(sentence)
                if not text:
                    continue
                t0 = time.perf_counter()
                first = True
                for chunk in self.tts.stream_pcm(text, previous_text=spoken[-400:] or None):
                    if stop.is_set():
                        break
                    if first:
                        log.debug("TTS erster Ton nach %.2fs: %r", time.perf_counter() - t0, text[:40])
                        first = False
                    if chunk:
                        _put(audio, chunk, stop)
                spoken = f"{spoken} {text}".strip()
        except BaseException as exc:  # noqa: BLE001 - wird im Aufrufer erneut ausgelöst
            errors.append(exc)
            stop.set()
        finally:
            _put(audio, _END, None)
            if stop.is_set():  # übrige Sätze verwerfen, damit der Hauptfaden nicht blockiert
                _drain(sentences)

    # --- Faden 2: Audio abspielen ---
    def _play(self, audio: queue.Queue, stop: threading.Event, errors: list,
              on_audio_start: Callable[[], None] | None) -> None:
        player = None
        try:
            while True:
                chunk = audio.get()
                if chunk is _END:
                    break
                if stop.is_set():
                    continue  # bis zur Ende-Markierung leeren, damit der Abruf nicht hängt
                if player is None:
                    player = self._player_factory()
                    if on_audio_start:
                        on_audio_start()
                player.write(chunk)
            if player is not None:
                if stop.is_set():
                    player.abort()
                else:
                    player.finish()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            stop.set()
            if player is not None:
                try:
                    player.abort()
                except Exception:  # noqa: BLE001
                    pass
            _drain(audio, until_end=True)


def _put(q: queue.Queue, item, stop: threading.Event | None) -> None:
    """Legt item in die Queue, gibt bei Abbruch aber nicht auf ewig den Faden her."""
    while True:
        try:
            q.put(item, timeout=0.1)
            return
        except queue.Full:
            if stop is not None and stop.is_set():
                return


def _drain(q: queue.Queue, until_end: bool = False) -> None:
    while True:
        try:
            item = q.get() if until_end else q.get_nowait()
        except queue.Empty:
            return
        if until_end and item is _END:
            return


def iter_text(deltas: Iterable[str], on_text: Callable[[str], None] | None = None) -> Iterator[str]:
    """Reicht Text-Häppchen durch und meldet den bisherigen Gesamttext (ohne Sprachausgabe)."""
    parts: list[str] = []
    for delta in deltas:
        parts.append(delta)
        if on_text:
            on_text("".join(parts))
        yield delta
