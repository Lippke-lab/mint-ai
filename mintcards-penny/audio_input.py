"""Push-to-Talk-Aufnahme vom Mikrofon. Liefert WAV-Bytes im Arbeitsspeicher."""

from __future__ import annotations

import io
import logging
import threading
import wave

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

CHANNELS = 1
DTYPE = "int16"
MIN_SECONDS = 0.3  # kürzere Aufnahmen gelten als versehentlicher Tastendruck


class Recorder:
    """Nimmt zwischen start() und stop() Audio auf."""

    def __init__(self, sample_rate: int, device: str | int | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        if status:
            log.debug("Audio-Status: %s", status)
        self._frames.append(indata.copy())

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> bytes | None:
        """Stoppt die Aufnahme und gibt WAV-Bytes zurück (None, wenn zu kurz)."""
        with self._lock:
            if self._stream is None:
                return None
            self._stream.stop()
            self._stream.close()
            self._stream = None
            frames, self._frames = self._frames, []

        if not frames:
            return None
        audio = np.concatenate(frames, axis=0)
        duration = len(audio) / self.sample_rate
        if duration < MIN_SECONDS:
            log.info("Aufnahme zu kurz (%.2fs), wird ignoriert.", duration)
            return None
        log.debug("Aufnahme: %.1fs", duration)
        return to_wav_bytes(audio, self.sample_rate)


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


def _parse_key(name: str):
    from pynput import keyboard

    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    try:
        return getattr(keyboard.Key, name)
    except AttributeError as exc:
        raise ValueError(
            f"Unbekannte PTT_KEY '{name}'. Beispiele: space, f9, ctrl_r, alt_r oder ein Buchstabe."
        ) from exc


class PushToTalk:
    """Wartet auf eine Push-to-Talk-Eingabe und liefert die Aufnahme als WAV.

    mode="hold":  Taste gedrückt halten = aufnehmen, loslassen = fertig.
                  Nutzt pynput und reagiert auch, wenn das Terminal nicht im Fokus ist.
    mode="enter": Enter startet, Enter stoppt. Läuft rein im Terminal.
    """

    def __init__(self, recorder: Recorder, mode: str = "hold", key: str = "space"):
        self.recorder = recorder
        self.mode = mode
        self.key_name = key
        self._listener = None
        self._armed = threading.Event()
        self._done = threading.Event()
        self._result: bytes | None = None

        if mode == "hold":
            from pynput import keyboard

            self._key = _parse_key(key)
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.daemon = True
            self._listener.start()

    @property
    def hint(self) -> str:
        if self.mode == "hold":
            return f"[{self.key_name.upper()}] gedrückt halten und sprechen, loslassen zum Senden."
        return "[ENTER] drücken, sprechen, [ENTER] zum Senden."

    # --- pynput Callbacks (laufen im Listener-Thread) ---
    def _matches(self, key) -> bool:
        return key == self._key

    def _on_press(self, key):
        if not self._armed.is_set() or not self._matches(key):
            return
        if not self.recorder.is_recording:  # Tasten-Autorepeat ignorieren
            try:
                self.recorder.start()
                print("  ● Aufnahme läuft ...", flush=True)
            except Exception as exc:  # noqa: BLE001
                log.error("Mikrofon konnte nicht gestartet werden: %s", exc)
                self._result = None
                self._done.set()

    def _on_release(self, key):
        if not self._armed.is_set() or not self._matches(key) or not self.recorder.is_recording:
            return
        self._result = self.recorder.stop()
        self._armed.clear()
        self._done.set()

    # --- öffentliche API ---
    def listen(self) -> bytes | None:
        """Blockiert bis eine Aufnahme fertig ist. Ctrl+C bricht ab."""
        if self.mode == "enter":
            return self._listen_enter()

        self._result = None
        self._done.clear()
        self._armed.set()
        try:
            # Mit Timeout warten, damit Ctrl+C im Hauptthread ankommt.
            while not self._done.wait(timeout=0.1):
                pass
        finally:
            self._armed.clear()
            if self.recorder.is_recording:
                self.recorder.stop()
        return self._result

    def _listen_enter(self) -> bytes | None:
        input()
        self.recorder.start()
        print("  ● Aufnahme läuft ... [ENTER] zum Senden", flush=True)
        try:
            input()
        finally:
            result = self.recorder.stop()
        return result

    def close(self) -> None:
        if self._listener is not None:
            self._listener.stop()


if __name__ == "__main__":
    # Einzeltest: Mikrofon aufnehmen und als test_aufnahme.wav speichern.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config_or_exit

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config_or_exit(require_keys=())
    print("Verfügbare Eingabegeräte:")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            print(f"  [{idx}] {dev['name']}")
    ptt = PushToTalk(Recorder(cfg.sample_rate, cfg.input_device), cfg.ptt_mode, cfg.ptt_key)
    print("\n" + ptt.hint)
    try:
        wav = ptt.listen()
    except KeyboardInterrupt:
        sys.exit(0)
    finally:
        ptt.close()
    if wav:
        out = Path(__file__).parent / "test_aufnahme.wav"
        out.write_bytes(wav)
        print(f"Gespeichert: {out} ({len(wav) / 1024:.0f} KB)")
    else:
        print("Keine verwertbare Aufnahme.")
