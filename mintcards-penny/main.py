"""MintCards Penny: Push-to-Talk -> ElevenLabs STT -> Claude -> ElevenLabs TTS."""

from __future__ import annotations

import logging
import sys
import time

import anthropic
from elevenlabs.core.api_error import ApiError as ElevenLabsError

from claude_brain import ClaudeBrain, EchoBrain, Memory
from config import REQUIRED_KEYS, SYSTEM_PROMPT_FILE, load_config_or_exit

log = logging.getLogger("penny")

# Sprachbefehle, die lokal verarbeitet werden, ohne Claude zu fragen.
RESET_COMMANDS = ("neues gespräch", "vergiss alles", "reset")


def setup_logging() -> None:
    level = logging.DEBUG if "--debug" in sys.argv else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    # Bibliotheken nur bei Warnungen zu Wort kommen lassen
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "elevenlabs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def elevenlabs_error_text(exc: ElevenLabsError) -> str:
    if exc.status_code == 401:
        return "ElevenLabs lehnt den API-Key ab (401). Prüfe ELEVENLABS_API_KEY."
    if exc.status_code == 404:
        return "ElevenLabs findet Stimme oder Modell nicht (404). Prüfe ELEVENLABS_VOICE_ID."
    return f"ElevenLabs-Fehler {exc.status_code}: {exc.body}"


def run_turn(ptt, stt, brain, tts, turn: int) -> None:
    wav = ptt.listen()
    if not wav:
        return

    t0 = time.perf_counter()
    text = stt.transcribe(wav)
    t_stt = time.perf_counter() - t0
    if not text:
        log.info("Nichts verstanden.")
        return
    log.info("[%d] DU     (%.1fs STT): %s", turn, t_stt, text)

    if text.lower().strip(" .!?") in RESET_COMMANDS:
        brain.reset()
        log.info("[%d] Verlauf gelöscht.", turn)
        tts.speak("Erledigt. Wir fangen von vorne an.")
        return

    t0 = time.perf_counter()
    answer = brain.ask(text)
    log.info("[%d] PENNY  (%.1fs Claude): %s", turn, time.perf_counter() - t0, answer)

    t0 = time.perf_counter()
    tts.speak(answer)
    log.debug("TTS + Wiedergabe: %.1fs", time.perf_counter() - t0)


def main() -> int:
    setup_logging()
    # --ohne-claude: Penny wiederholt nur, was sie verstanden hat (kein Anthropic-Key nötig)
    echo_mode = "--ohne-claude" in sys.argv
    required = tuple(k for k in REQUIRED_KEYS if not (echo_mode and k == "ANTHROPIC_API_KEY"))
    cfg = load_config_or_exit(required)

    try:
        # Audio-Module erst nach der Key-Prüfung laden, damit Fehler klar getrennt sind.
        from audio_input import PushToTalk, Recorder
        from stt_elevenlabs import SpeechToText
        from tts_elevenlabs import TextToSpeech
    except OSError as exc:
        print(f"[FEHLER] Audio-System nicht verfügbar: {exc}\n"
              "Linux: sudo apt install libportaudio2  |  macOS: brew install portaudio",
              file=sys.stderr)
        return 2

    try:
        if echo_mode:
            brain = EchoBrain()
        else:
            brain = ClaudeBrain(cfg.anthropic_api_key, cfg.claude_model, SYSTEM_PROMPT_FILE,
                                cfg.history_turns, cfg.claude_effort, Memory(cfg.memory_file))
    except (FileNotFoundError, ValueError) as exc:
        print(f"[FEHLER] {exc}", file=sys.stderr)
        return 2

    stt = SpeechToText(cfg.elevenlabs_api_key, cfg.stt_model, cfg.language)
    tts = TextToSpeech(cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id, cfg.tts_model, cfg.language)
    try:
        ptt = PushToTalk(Recorder(cfg.sample_rate, cfg.input_device), cfg.ptt_mode, cfg.ptt_key)
    except Exception as exc:  # noqa: BLE001 - z. B. pynput ohne Display / fehlende Rechte
        print(f"[FEHLER] Push-to-Talk konnte nicht gestartet werden: {exc}\n"
              "Tipp: Setze PTT_MODE=enter in der .env.", file=sys.stderr)
        return 2

    print("\n=== MintCards Penny ===")
    print(f"Modell: {'echo (ohne Claude)' if echo_mode else cfg.claude_model} | Stimme: {cfg.tts_model} | STT: {cfg.stt_model}")
    print(ptt.hint)
    print('Sag "neues Gespräch" zum Zurücksetzen. Ctrl+C beendet.\n')

    turn = 0
    try:
        while True:
            turn += 1
            try:
                run_turn(ptt, stt, brain, tts, turn)
            except anthropic.AuthenticationError:
                log.error("Anthropic lehnt den API-Key ab. Prüfe ANTHROPIC_API_KEY.")
                return 1
            except anthropic.RateLimitError:
                log.warning("Anthropic Rate-Limit erreicht. Kurz warten und nochmal versuchen.")
            except anthropic.APIStatusError as exc:
                log.error("Anthropic-Fehler %s: %s", exc.status_code, exc.message)
            except anthropic.APIConnectionError:
                log.error("Keine Verbindung zur Anthropic API. Internet prüfen.")
            except ElevenLabsError as exc:
                log.error(elevenlabs_error_text(exc))
                if exc.status_code == 401:
                    return 1
            except OSError as exc:  # Audio-Geräte, Netzwerk-Sockets
                log.error("Audio/IO-Fehler: %s", exc)
            except Exception as exc:  # noqa: BLE001 - Loop soll bei Einzelfehlern weiterlaufen
                log.error("Unerwarteter Fehler (%s): %s", type(exc).__name__, exc)
                log.debug("Details", exc_info=True)
            print(ptt.hint)
    except KeyboardInterrupt:
        print("\nPenny fährt herunter. Bis später.")
        return 0
    finally:
        ptt.close()


if __name__ == "__main__":
    sys.exit(main())
