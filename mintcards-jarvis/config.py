"""Lädt die Konfiguration aus der .env-Datei und prüft Pflichtwerte."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
SYSTEM_PROMPT_FILE = BASE_DIR / "system_prompt.txt"

REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")


class ConfigError(Exception):
    """Fehlende oder ungültige Konfiguration."""


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    claude_model: str
    claude_effort: str
    history_turns: int
    tts_model: str
    stt_model: str
    language: str
    ptt_mode: str
    ptt_key: str
    sample_rate: int
    input_device: str | int | None


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} muss eine Zahl sein, ist aber '{raw}'.") from exc


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.getenv(name, "").strip().lower() or default
    if value not in allowed:
        raise ConfigError(f"{name}='{value}' ist ungültig. Erlaubt: {', '.join(allowed)}.")
    return value


def load_config(require_keys: tuple[str, ...] = REQUIRED_KEYS) -> Config:
    """Lädt .env und gibt eine Config zurück.

    `require_keys` erlaubt den Einzeltests, nur die Keys zu prüfen, die sie brauchen.
    """
    load_dotenv(ENV_FILE)

    missing = [k for k in require_keys if not os.getenv(k, "").strip()]
    if missing:
        hint = (
            f"Fehlende Konfiguration: {', '.join(missing)}\n"
            f"Lege die Datei {ENV_FILE} an (Vorlage: .env.example) und trage die Werte ein."
        )
        if os.getenv("GITHUB_ACTIONS"):
            hint = (
                f"Fehlende GitHub Secrets: {', '.join(missing)}\n"
                "Anlegen unter: Repo → Settings → Secrets and variables → Actions → New repository secret."
            )
        elif not ENV_FILE.exists():
            hint += "\nHinweis: Die Datei .env existiert noch nicht."
        raise ConfigError(hint)

    device_raw = os.getenv("INPUT_DEVICE", "").strip()
    input_device: str | int | None = None
    if device_raw:
        input_device = int(device_raw) if device_raw.isdigit() else device_raw

    history_turns = _int("HISTORY_TURNS", 10)
    if history_turns < 1:
        raise ConfigError("HISTORY_TURNS muss mindestens 1 sein.")

    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        claude_model=os.getenv("CLAUDE_MODEL", "").strip() or "claude-sonnet-5",
        claude_effort=_choice("CLAUDE_EFFORT", "low", ("low", "medium", "high")),
        history_turns=history_turns,
        tts_model=os.getenv("ELEVENLABS_TTS_MODEL", "").strip() or "eleven_flash_v2_5",
        stt_model=os.getenv("ELEVENLABS_STT_MODEL", "").strip() or "scribe_v2",
        language=os.getenv("LANGUAGE", "").strip() or "de",
        ptt_mode=_choice("PTT_MODE", "hold", ("hold", "enter")),
        ptt_key=os.getenv("PTT_KEY", "").strip().lower() or "space",
        sample_rate=_int("SAMPLE_RATE", 16000),
        input_device=input_device,
    )


def load_config_or_exit(require_keys: tuple[str, ...] = REQUIRED_KEYS) -> Config:
    """Wie load_config, beendet das Programm aber mit klarer Meldung statt Traceback."""
    try:
        return load_config(require_keys)
    except ConfigError as exc:
        print(f"\n[KONFIGURATIONSFEHLER]\n{exc}\n", file=sys.stderr)
        sys.exit(2)
