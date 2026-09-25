"""Wiedergabe von rohem PCM-Audio (16 bit, mono) über sounddevice."""

from __future__ import annotations

import numpy as np
import sounddevice as sd

WRITE_BYTES = 4096  # kleine Stücke, damit ein Abbruch (Barge-in) schnell greift


def play_pcm(pcm: bytes, sample_rate: int) -> None:
    """Spielt 16-bit Mono-PCM ab und blockiert, bis die Wiedergabe fertig ist."""
    if not pcm:
        return
    if len(pcm) % 2:  # ungerade Byteanzahl kann bei Streams vorkommen
        pcm = pcm[:-1]
    audio = np.frombuffer(pcm, dtype=np.int16)
    sd.play(audio, samplerate=sample_rate)
    try:
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        raise


def stop() -> None:
    """Bricht eine laufende play_pcm-Wiedergabe ab."""
    sd.stop()


class PcmPlayer:
    """Spielt PCM-Häppchen ab, sobald sie ankommen (für Streaming-TTS).

    write() blockiert nur so lange, bis im Ausgabepuffer Platz ist, also etwa im
    Tempo der Wiedergabe. finish() wartet das Ende ab, abort() bricht sofort ab.
    """

    def __init__(self, sample_rate: int):
        self._rest = b""
        self._stream = sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16")
        self._stream.start()

    def write(self, pcm: bytes) -> None:
        data = self._rest + pcm
        cut = len(data) - len(data) % 2  # nur ganze 16-bit-Samples schreiben
        data, self._rest = data[:cut], data[cut:]
        for i in range(0, len(data), WRITE_BYTES):
            self._stream.write(data[i:i + WRITE_BYTES])

    def finish(self) -> None:
        """Wartet, bis alles gespielt ist, und schließt den Ausgabestrom."""
        try:
            self._stream.stop()  # stop() spielt den restlichen Puffer noch aus
        finally:
            self._stream.close()

    def abort(self) -> None:
        """Bricht sofort ab, der restliche Puffer wird verworfen."""
        try:
            self._stream.abort()
        finally:
            self._stream.close()
