"""Speech-to-Text über ElevenLabs Scribe."""

from __future__ import annotations

import io
import logging

from elevenlabs.client import ElevenLabs

log = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, api_key: str, model_id: str = "scribe_v2", language: str | None = "de"):
        self.client = ElevenLabs(api_key=api_key)
        self.model_id = model_id
        self.language = language

    def transcribe(self, wav_bytes: bytes) -> str:
        """Schickt WAV-Audio an Scribe und gibt den erkannten Text zurück."""
        audio = io.BytesIO(wav_bytes)
        audio.name = "aufnahme.wav"
        result = self.client.speech_to_text.convert(
            file=audio,
            model_id=self.model_id,
            language_code=self.language or None,
            tag_audio_events=False,  # keine "(lacht)"-Marker im Text
        )
        text = (getattr(result, "text", "") or "").strip()
        log.debug("STT-Ergebnis: %r", text)
        return text


if __name__ == "__main__":
    # Einzeltest: python stt_elevenlabs.py [pfad.wav]
    # Ohne Pfad wird test_aufnahme.wav aus `python audio_input.py` verwendet.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config_or_exit

    cfg = load_config_or_exit(require_keys=("ELEVENLABS_API_KEY",))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "test_aufnahme.wav"
    if not path.exists():
        sys.exit(f"Datei {path} nicht gefunden. Erst `python audio_input.py` ausführen.")
    stt = SpeechToText(cfg.elevenlabs_api_key, cfg.stt_model, cfg.language)
    print("Erkannt:", stt.transcribe(path.read_bytes()) or "(nichts)")
