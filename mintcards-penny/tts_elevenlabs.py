"""Text-to-Speech über ElevenLabs inkl. Wiedergabe."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

log = logging.getLogger(__name__)

# Rohes PCM spart einen MP3-Decoder (kein ffmpeg nötig) und spielt direkt über sounddevice.
PCM_FORMAT = "pcm_22050"
PCM_RATE = 22050


class TextToSpeech:
    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_flash_v2_5",
                 language: str | None = "de", speed: float | None = None):
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id
        self.model_id = model_id
        self.language = language
        self.speed = speed

    def _options(self, previous_text: str | None = None) -> dict:
        kwargs: dict = {}
        # language_code wird nur von einigen Modellen (z. B. Flash/Turbo v2.5) akzeptiert.
        if self.language and "v2_5" in self.model_id:
            kwargs["language_code"] = self.language
        # Vorheriger Satz als Kontext: gleichmäßige Betonung über mehrere Sätze hinweg.
        # eleven_v3 unterstützt das nicht.
        if previous_text and "v3" not in self.model_id:
            kwargs["previous_text"] = previous_text
        if self.speed is not None:
            kwargs["voice_settings"] = VoiceSettings(speed=self.speed)
        return kwargs

    def stream_pcm(self, text: str, previous_text: str | None = None) -> Iterator[bytes]:
        """Liefert die Sprachausgabe als 16-bit Mono-PCM (22,05 kHz), Stück für Stück."""
        yield from self.client.text_to_speech.stream(
            self.voice_id,
            text=text,
            model_id=self.model_id,
            output_format=PCM_FORMAT,
            **self._options(previous_text),
        )

    def synthesize(self, text: str) -> bytes:
        """Gibt die komplette Sprachausgabe als 16-bit Mono-PCM (22,05 kHz) zurück."""
        chunks = self.client.text_to_speech.convert(
            self.voice_id,
            text=text,
            model_id=self.model_id,
            output_format=PCM_FORMAT,
            **self._options(),
        )
        return b"".join(chunks)

    def speak(self, text: str) -> None:
        """Spricht text und blockiert bis zum Ende (Wiedergabe beginnt schon beim ersten Stück)."""
        if not text.strip():
            return
        from speech import SpeechOutput  # erst hier laden, damit synthesize() ohne Soundkarte läuft

        SpeechOutput(self).say(text)


if __name__ == "__main__":
    # Einzeltest: python tts_elevenlabs.py "Beliebiger Text"
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config_or_exit

    cfg = load_config_or_exit(require_keys=("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"))
    text = " ".join(sys.argv[1:]) or (
        "Systeme online. Mintcards steht bereit, Chef. Ich spreche jetzt Satz für Satz, "
        "damit du nicht warten musst."
    )
    TextToSpeech(cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id, cfg.tts_model, cfg.language,
                 cfg.tts_speed).speak(text)
    print("Wiedergabe beendet.")
