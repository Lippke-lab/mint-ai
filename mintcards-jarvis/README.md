# MintCards Jarvis

Sprachassistent im Jarvis-Stil für das Pokémon-Karten-Business **Mintcards**.

```
Mikrofon → ElevenLabs Scribe (STT) → Claude Sonnet → ElevenLabs TTS → Lautsprecher
```

Taste gedrückt halten, sprechen, loslassen, Antwort hören. Der Verlauf der letzten 10 Turns bleibt im Speicher, damit Rückfragen funktionieren.

## Dateien

| Datei | Aufgabe |
|---|---|
| `main.py` | Hauptschleife, Logging, Fehlerbehandlung, sauberer Exit per Ctrl+C |
| `config.py` | Lädt `.env`, prüft Pflicht-Keys, liefert klare Fehlermeldungen |
| `audio_input.py` | Push-to-Talk-Aufnahme, WAV im Arbeitsspeicher |
| `audio_output.py` | Wiedergabe von PCM-Audio |
| `stt_elevenlabs.py` | Sprache zu Text über ElevenLabs Scribe |
| `tts_elevenlabs.py` | Text zu Sprache über ElevenLabs und Abspielen |
| `claude_brain.py` | Gesprächsverlauf plus Aufruf von Claude über die Anthropic API |
| `smoke_test.py` | API-Test von Claude, TTS und STT ohne Audio-Hardware (auch in GitHub Actions) |
| `system_prompt.txt` | Persönlichkeit und Regeln von Jarvis. **Hier frei anpassen, ohne Code anzufassen** |

## 1. Keys besorgen

1. **Anthropic API-Key:** https://console.anthropic.com → *API Keys* → *Create Key*. Konto braucht Guthaben.
2. **ElevenLabs API-Key:** https://elevenlabs.io → Profil → *API Keys*. Der Key braucht Rechte für *Text to Speech* und *Speech to Text*.
3. **ElevenLabs Voice-ID:** Im ElevenLabs-Dashboard unter *Voices* eine Stimme wählen (oder in der Voice Library hinzufügen) → *ID kopieren*.

## 2. Installation

Voraussetzung: Python 3.11 oder neuer.

```bash
cd mintcards-jarvis
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Audio-Bibliothek (PortAudio), falls nicht vorhanden:

- **Windows:** kommt mit `sounddevice` mit, nichts zu tun.
- **macOS:** `brew install portaudio`
- **Linux:** `sudo apt install libportaudio2`

## 3. `.env` ausfüllen

```bash
cp .env.example .env
```

Dann `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY` und `ELEVENLABS_VOICE_ID` eintragen. Alle weiteren Werte sind optional und in `.env.example` erklärt. Die `.env` steht in `.gitignore` und landet nie im Repo. Fehlt ein Key, bricht das Programm mit einer klaren Meldung ab.

## 4. Einzeln testen (vor der vollen Schleife)

Die Tests laufen in dieser Reihenfolge, jeder prüft genau einen Baustein:

```bash
# a) Mikrofon: Taste halten, sprechen, loslassen → test_aufnahme.wav
#    Listet auch alle Eingabegeräte (Index für INPUT_DEVICE)
python audio_input.py

# b) STT: transkribiert test_aufnahme.wav (oder eine eigene Datei)
python stt_elevenlabs.py
python stt_elevenlabs.py pfad/zu/datei.wav

# c) Claude: reiner Text-Chat im Terminal, ganz ohne Audio
python claude_brain.py

# d) TTS: spricht einen Testsatz mit deiner Stimme
python tts_elevenlabs.py "Systeme online. Mintcards steht bereit."
```

Funktionieren alle vier, die volle Schleife starten.

### Alternative: API-Test über GitHub (ohne eigenen Rechner)

Mikrofon und Lautsprecher lassen sich nur lokal testen. Die drei Dienste (Claude, TTS, STT) prüft aber auch GitHub Actions:

1. Im Repo unter **Settings → Secrets and variables → Actions → New repository secret** drei Secrets anlegen: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.
2. Im Tab **Actions** links **Jarvis API-Test** wählen → **Run workflow**. Optional eine eigene Testfrage eintragen.
3. Nach ca. 1 Minute zeigt der Lauf eine Tabelle mit ✅/❌ pro Schritt. Unter **Artifacts → jarvis-audio** liegt Jarvis' gesprochene Antwort als WAV zum Anhören.

Ablauf: Claude beantwortet die Testfrage, ElevenLabs spricht die Antwort, Scribe wandelt die Aufnahme zurück in Text. Lokal geht dasselbe mit `python smoke_test.py`.

## 5. Starten

```bash
python main.py            # normal
python main.py --debug    # zusätzlich Token-Zahlen, Latenzen, Fehlerdetails
```

- **Leertaste halten** = aufnehmen, **loslassen** = senden.
- Sag **"neues Gespräch"**, um den Verlauf zu löschen.
- **Ctrl+C** beendet.

Im Terminal wird jeder Turn mitgeloggt:

```
14:02:11 INFO    [1] DU     (0.8s STT): Was bringt ein Glurak ex aus Obsidianflammen gerade?
14:02:13 INFO    [1] JARVIS (1.9s Claude): Die Special Illustration Rare liegt grob bei ...
```

## Push-to-Talk-Modi

| `PTT_MODE` | Verhalten |
|---|---|
| `hold` (Standard) | Taste gedrückt halten. Nutzt `pynput`, reagiert **global**, also auch wenn das Terminal nicht im Fokus ist. |
| `enter` | Enter startet, Enter stoppt. Nur im Terminal, braucht keinerlei Sonderrechte. |

Hinweise zu `hold`:

- **macOS:** Terminal (bzw. iTerm/VS Code) braucht unter *Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen* und *Eingabeüberwachung* die Freigabe.
- **Linux:** funktioniert unter X11. Unter Wayland liefert `pynput` meist keine Tasten, dann `PTT_MODE=enter` nutzen.
- Weil der Hotkey global ist, nimmt auch Leertaste in anderen Programmen auf. Wer das nicht will, setzt z. B. `PTT_KEY=f9` oder `PTT_KEY=ctrl_r`.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `PortAudio library not found` | PortAudio installieren (siehe Installation) |
| Keine Reaktion auf Leertaste | macOS-Rechte prüfen, unter Wayland `PTT_MODE=enter` |
| Falsches Mikrofon | `python audio_input.py` zeigt Geräte, dann `INPUT_DEVICE=<Index>` |
| `401` von ElevenLabs | API-Key oder dessen Berechtigungen (TTS/STT) prüfen |
| `404` von ElevenLabs | Voice-ID prüfen |
| Antworten zu lang oder zu förmlich | `system_prompt.txt` anpassen, Neustart genügt |

## Ausbaustufen (noch nicht umgesetzt)

- Wake-Word statt Push-to-Talk (Porcupine / OpenWakeWord)
- Tool-Use: Preisabfrage, Einkaufsliste, Bestandsabfrage
- Persistenter Verlauf über Neustarts (JSON)
- Unterbrechbare Sprachausgabe (Barge-in), Grundlage ist `audio_output.stop()`
