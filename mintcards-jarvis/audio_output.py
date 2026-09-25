"""Wiedergabe von rohem PCM-Audio (16 bit, mono) über sounddevice."""

from __future__ import annotations

import numpy as np
import sounddevice as sd


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
    """Bricht eine laufende Wiedergabe ab (Grundlage für späteres Barge-in)."""
    sd.stop()
