"""Das "Hirn": verwaltet Gesprächsverlauf und ruft Claude über die Anthropic API auf."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import anthropic

log = logging.getLogger(__name__)

MAX_TOKENS = 4000  # Antworten sind kurz, Puffer für adaptives Denken


def load_system_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"System-Prompt-Datei fehlt: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"System-Prompt-Datei ist leer: {path}")
    return text


class Memory:
    """Speichert den Gesprächsverlauf als JSON-Datei, damit Penny ihn nach Neustarts noch kennt."""

    VERSION = 1

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            messages = data["messages"]
            valid = all(
                isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)
                for m in messages
            )
            if not valid:
                raise ValueError("unerwartetes Format")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            backup = self.path.with_suffix(".defekt.json")
            log.warning("Gedächtnisdatei %s unlesbar (%s). Sicherung: %s. Starte mit leerem Gedächtnis.",
                        self.path.name, exc, backup.name)
            try:
                self.path.replace(backup)
            except OSError:
                pass
            return []
        # Die API erwartet, dass der Verlauf mit einer Nutzer-Nachricht beginnt.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def save(self, messages: list[dict]) -> None:
        data = {
            "version": self.VERSION,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "messages": messages,
        }
        # Erst in Temp-Datei schreiben, dann ersetzen: bei Absturz bleibt die alte Datei heil.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


class ClaudeBrain:
    def __init__(self, api_key: str, model: str, system_prompt_path: Path,
                 history_turns: int = 10, effort: str = "low", memory: Memory | None = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.effort = effort
        self.system_prompt_path = system_prompt_path
        self.system_prompt = load_system_prompt(system_prompt_path)
        self.history_turns = history_turns
        self.memory = memory
        self.history: list[dict] = memory.load() if memory else []  # abwechselnd user / assistant
        self._trim()
        if self.history:
            log.info("Gedächtnis geladen: %d frühere Turns.", len(self.history) // 2)

    def reload_system_prompt(self) -> None:
        self.system_prompt = load_system_prompt(self.system_prompt_path)

    def reset(self) -> None:
        self.history.clear()
        self._persist()

    def _persist(self) -> None:
        if not self.memory:
            return
        try:
            self.memory.save(self.history)
        except OSError as exc:
            log.error("Gedächtnis konnte nicht gespeichert werden: %s", exc)

    def _trim(self) -> None:
        # Ein Turn = Nutzer-Nachricht + Antwort. Ältere Turns fliegen raus.
        max_messages = self.history_turns * 2
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

    def ask(self, user_text: str) -> str:
        """Schickt user_text samt Verlauf an Claude und gibt die Antwort zurück.

        API-Fehler werden als anthropic.APIError weitergereicht; der Verlauf
        bleibt dann unverändert, damit ein erneuter Versuch sauber ist.
        """
        messages = self.history + [{"role": "user", "content": user_text}]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_prompt,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
        )

        if response.stop_reason == "refusal":
            log.warning("Claude hat die Anfrage abgelehnt: %s", response.stop_details)
            return "Dazu kann ich leider nichts sagen."

        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "max_tokens":
            log.warning("Antwort wurde bei max_tokens abgeschnitten.")
        if not answer:
            answer = "Da ist mir gerade nichts eingefallen. Frag bitte nochmal."

        log.debug("Tokens: in=%s out=%s cache_read=%s", response.usage.input_tokens,
                  response.usage.output_tokens, response.usage.cache_read_input_tokens)

        self.history = messages + [{"role": "assistant", "content": answer}]
        self._trim()
        self._persist()
        return answer


class EchoBrain:
    """Ersatz-Hirn ohne API: wiederholt, was verstanden wurde.

    Zum Testen von Mikrofon, Push-to-Talk, STT und TTS ohne Anthropic-Guthaben.
    """

    model = "echo (ohne Claude)"

    def reset(self) -> None:
        pass

    def ask(self, user_text: str) -> str:
        return f"Verstanden: {user_text}"


if __name__ == "__main__":
    # Einzeltest: Text-Chat mit Claude im Terminal, ganz ohne Audio.
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from config import SYSTEM_PROMPT_FILE, load_config_or_exit

    cfg = load_config_or_exit(require_keys=("ANTHROPIC_API_KEY",))
    brain = ClaudeBrain(cfg.anthropic_api_key, cfg.claude_model, SYSTEM_PROMPT_FILE,
                        cfg.history_turns, cfg.claude_effort, Memory(cfg.memory_file))
    print(f"Text-Chat mit {cfg.claude_model}. Leere Zeile oder Ctrl+C beendet.")
    try:
        while (text := input("\nDu: ").strip()):
            print("Penny:", brain.ask(text))
    except (KeyboardInterrupt, EOFError):
        pass
