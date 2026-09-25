"""Text-to-Speech über ElevenLabs inkl. Wiedergabe."""

from __future__ import annotations

import logging

from elevenlabs.client import ElevenLabs

import audio_output

log = logging.getLogger(__name__)

# Rohes PCM spart einen MP3-Decoder (kein ffmpeg nötig) und spielt direkt über sounddevice.
PCM_FORMAT = "pcm_22050"
PCM_RATE = 22050


class TextToSpeech:
    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_flash_v2_5",
                 language: str | None = "de"):
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id
        self.model_id = model_id
        self.language = language

    def synthesize(self, text: str) -> bytes:
        """Gibt die Sprachausgabe als 16-bit Mono-PCM (22,05 kHz) zurück."""
        kwargs = {}
        # language_code wird nur von einigen Modellen (z. B. Flash/Turbo v2.5) akzeptiert.
        if self.language and "v2_5" in self.model_id:
            kwargs["language_code"] = self.language
        chunks = self.client.text_to_speech.convert(
            self.voice_id,
            text=text,
            model_id=self.model_id,
            output_format=PCM_FORMAT,
            **kwargs,
        )
        return b"".join(chunks)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        audio_output.play_pcm(self.synthesize(text), PCM_RATE)


if __name__ == "__main__":
    # Einzeltest: python tts_elevenlabs.py "Beliebiger Text"
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config_or_exit

    cfg = load_config_or_exit(require_keys=("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"))
    text = " ".join(sys.argv[1:]) or "Systeme online. Mintcards steht bereit, Chef."
    TextToSpeech(cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id, cfg.tts_model, cfg.language).speak(text)
    print("Wiedergabe beendet.")
