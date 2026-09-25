"""API-Smoke-Test ohne Mikrofon und Lautsprecher (z. B. für GitHub Actions).

Prüft nacheinander:
  1. Claude:  Testfrage schicken, Antwort muss kommen
  2. TTS:     Claudes Antwort in Sprache umwandeln, als WAV speichern
  3. STT:     diese WAV zurück in Text umwandeln

Aufruf:  python smoke_test.py [--out ordner]
Exit-Code 0 = alles ok, 1 = mindestens ein Schritt fehlgeschlagen, 2 = Konfiguration fehlt.
"""

from __future__ import annotations

import argparse
import os
import time
import traceback
import wave
from pathlib import Path

from claude_brain import ClaudeBrain
from config import SYSTEM_PROMPT_FILE, load_config_or_exit
from stt_elevenlabs import SpeechToText
from tts_elevenlabs import PCM_RATE, TextToSpeech

DEFAULT_QUESTION = "Stell dich in einem Satz vor und sag, wobei du Mintcards hilfst."


def pcm_to_wav(pcm: bytes, sample_rate: int, path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="smoke_output", help="Ordner für die erzeugte Audiodatei")
    parser.add_argument("--question", default=os.getenv("SMOKE_QUESTION") or DEFAULT_QUESTION)
    args = parser.parse_args()

    cfg = load_config_or_exit()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / "jarvis_antwort.wav"

    results: list[tuple[str, bool, str]] = []

    def step(name: str, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            results.append((name, True, f"{detail} ({time.perf_counter() - t0:.1f}s)"))
            print(f"[OK]     {name}: {detail}")
            return True
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
            print(f"[FEHLER] {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return False

    state: dict[str, object] = {}

    def claude():
        brain = ClaudeBrain(cfg.anthropic_api_key, cfg.claude_model, SYSTEM_PROMPT_FILE,
                            cfg.history_turns, cfg.claude_effort)
        state["answer"] = brain.ask(args.question)
        return f"{cfg.claude_model} sagt: {state['answer']}"

    def tts():
        text = str(state.get("answer") or "Systeme online. Mintcards steht bereit.")
        pcm = TextToSpeech(cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id, cfg.tts_model,
                           cfg.language).synthesize(text)
        if len(pcm) < PCM_RATE:  # weniger als ~0,5s Audio ist verdächtig
            raise RuntimeError(f"Nur {len(pcm)} Bytes Audio erhalten")
        pcm_to_wav(pcm, PCM_RATE, wav_path)
        return f"{cfg.tts_model}, {len(pcm) / 2 / PCM_RATE:.1f}s Audio → {wav_path}"

    def stt():
        if not wav_path.exists():
            raise RuntimeError("Keine Audiodatei aus dem TTS-Schritt vorhanden")
        text = SpeechToText(cfg.elevenlabs_api_key, cfg.stt_model, cfg.language).transcribe(
            wav_path.read_bytes())
        if not text:
            raise RuntimeError("Leeres Transkript")
        return f"{cfg.stt_model} erkennt: {text}"

    step("Claude", claude)
    step("Sprachausgabe (TTS)", tts)
    step("Spracherkennung (STT)", stt)

    ok = all(r[1] for r in results)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## MintCards Jarvis: API-Test\n\n| Schritt | Status | Details |\n|---|---|---|\n")
            for name, passed, detail in results:
                safe = detail.replace("|", "\\|").replace("\n", " ")
                fh.write(f"| {name} | {'✅' if passed else '❌'} | {safe} |\n")
            if wav_path.exists():
                fh.write("\nDie Audiodatei liegt unten unter **Artifacts → jarvis-audio** zum Download.\n")
    print("\nERGEBNIS:", "alles ok" if ok else "mindestens ein Schritt fehlgeschlagen")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
