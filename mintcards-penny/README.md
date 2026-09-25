# MintCards Penny

Penny, die Sprachassistentin im Jarvis-Stil für das Pokémon-Karten-Business **Mintcards**.

```
Mikrofon → ElevenLabs Scribe (STT) → Claude Sonnet (Stream) → Satz für Satz → ElevenLabs TTS (Stream) → Lautsprecher
```

**Q + E** gleichzeitig gedrückt halten, sprechen, loslassen, Antwort hören. Penny fängt schon mit dem ersten Satz an zu sprechen, während Claude den Rest noch schreibt. **Q + E während sie spricht** = sie hört sofort auf und du bist dran. Penny merkt sich die letzten 10 Turns in `penny_gedaechtnis.json`, auch über Neustarts hinweg.

## Schnellstart im Browser (ohne Installation)

`penny.html` ist Penny komplett in einer einzigen Datei: Mikrofon, Spracherkennung, Claude, Stimme und Gedächtnis laufen direkt im Browser. Python, PortAudio oder pynput braucht es dafür nicht.

1. `penny.html` im Browser öffnen (Chrome oder Edge empfohlen, Doppelklick reicht meistens).
2. Die Einstellungen öffnen sich: Anthropic-Key, ElevenLabs-Key und Voice-ID eintragen, **Verbindung testen**, **Speichern**.
3. **Penny starten** tippen, Mikrofon erlauben. Penny begrüßt dich.
4. **Leertaste** oder **Q + E** halten (oder den großen Button gedrückt halten), sprechen, loslassen.
5. Während Penny spricht: Taste oder Button drücken = sie hört sofort auf.

Blockiert der Browser bei Doppelklick das Mikrofon, die Seite über einen lokalen Server öffnen:

```bash
cd mintcards-penny
python -m http.server 8000
# dann http://localhost:8000/penny.html öffnen
```

**Wichtig zu den Keys:** Sie werden nur in diesem Browser gespeichert (nur mit Haken bei "Keys auf diesem Gerät merken", sonst nur bis zum Schließen des Tabs). Wer an deinen Rechner kommt, kann sie dort auslesen. Die Datei darum nie auf einen Webserver hochladen oder mit eingetragenen Keys weitergeben. Die Datei selbst enthält keine Keys.

Unterschiede zur Python-Version: Die Tasten funktionieren nur, solange das Browserfenster im Vordergrund ist (dafür geht es auch per Finger auf dem Handy). Gedächtnis und Einstellungen liegen im Browser, nicht in `penny_gedaechtnis.json`. Persönlichkeit, Modell, Stimm-Modell und Tempo lassen sich unter **Mehr Einstellungen** ändern.

## Dateien

| Datei | Aufgabe |
|---|---|
| `main.py` | Hauptschleife, Logging, Fehlerbehandlung, sauberer Exit per Ctrl+C |
| `config.py` | Lädt `.env`, prüft Pflicht-Keys, liefert klare Fehlermeldungen |
| `audio_input.py` | Push-to-Talk-Aufnahme, WAV im Arbeitsspeicher |
| `audio_output.py` | Wiedergabe von PCM-Audio |
| `stt_elevenlabs.py` | Sprache zu Text über ElevenLabs Scribe |
| `tts_elevenlabs.py` | Text zu Sprache über ElevenLabs (gestreamt) |
| `speech.py` | Satzweise Sprachausgabe: zerlegt Claudes Text in Sätze, holt Audio vorab, spielt ohne Pausen, bricht bei Unterbrechung ab |
| `claude_brain.py` | Gesprächsverlauf plus Aufruf von Claude über die Anthropic API |
| `smoke_test.py` | API-Test von Claude, TTS und STT ohne Audio-Hardware (auch in GitHub Actions) |
| `tests/` | Unit-Tests ohne Keys und ohne Soundkarte (`python -m pytest tests`), laufen bei jedem Push |
| `dashboard.py` | Lokales Web-Dashboard, zeigt Pennys Zustand live |
| `dashboard/index.html` | Oberfläche des Dashboards |
| `assistant.py` | Penny als Ganzes: Hirn, Stimme, Status und Ereignisse fürs Dashboard |
| `penny.html` | Penny komplett im Browser, eine Datei, keine Installation |
| `tests/web/` | Browser-Test für `penny.html` (Chromium mit Fake-Mikrofon und nachgebauten APIs) |
| `system_prompt.txt` | Persönlichkeit und Regeln von Penny. **Hier frei anpassen, ohne Code anzufassen** |

## 1. Keys besorgen

1. **Anthropic API-Key:** https://console.anthropic.com → *API Keys* → *Create Key*. Konto braucht Guthaben.
2. **ElevenLabs API-Key:** https://elevenlabs.io → Profil → *API Keys*. Der Key braucht Rechte für *Text to Speech* und *Speech to Text*.
3. **ElevenLabs Voice-ID:** Im ElevenLabs-Dashboard unter *Voices* eine Stimme wählen (oder in der Voice Library hinzufügen) → *ID kopieren*.

## 2. Installation

Voraussetzung: Python 3.11 oder neuer.

```bash
cd mintcards-penny
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

# d) TTS: spricht mehrere Sätze mit deiner Stimme (gestreamt, Satz für Satz)
python tts_elevenlabs.py "Systeme online. Mintcards steht bereit."
```

Ohne Keys und ohne Mikrofon lässt sich die Logik jederzeit prüfen:

```bash
pip install pytest
python -m pytest tests
```

Funktionieren alle vier, die volle Schleife starten.

### Alternative: API-Test über GitHub (ohne eigenen Rechner)

Mikrofon und Lautsprecher lassen sich nur lokal testen. Die drei Dienste (Claude, TTS, STT) prüft aber auch GitHub Actions:

1. Im Repo unter **Settings → Secrets and variables → Actions → New repository secret** drei Secrets anlegen: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.
2. Im Tab **Actions** links **Penny API-Test** wählen → **Run workflow**. Optional eine eigene Testfrage eintragen.
3. Nach ca. 1 Minute zeigt der Lauf eine Tabelle mit ✅/❌ pro Schritt. Unter **Artifacts → penny-audio** liegt Pennys gesprochene Antwort als WAV zum Anhören.

Ablauf: Claude beantwortet die Testfrage, ElevenLabs spricht die Antwort, Scribe wandelt die Aufnahme zurück in Text. Lokal geht dasselbe mit `python smoke_test.py`. Ohne `ANTHROPIC_API_KEY` wird der Claude-Schritt übersprungen (⏭️), TTS und STT werden trotzdem geprüft.

## 5. Starten

```bash
python main.py            # normal
python main.py --debug    # zusätzlich Token-Zahlen, Latenzen, Fehlerdetails
python main.py --ohne-claude  # Test ohne Anthropic-Guthaben: Penny wiederholt nur, was sie verstanden hat
```

- Beim Start sagt Penny "Systeme online. Ich bin bereit, Chef." Hörst du das, funktionieren Key, Stimme und Lautsprecher. Abschalten oder eigener Satz: `BEGRUESSUNG` in der `.env`.
- **Q + E gleichzeitig halten** = aufnehmen, **eine davon loslassen** = senden.
- **Q + E drücken, während Penny spricht** = sie verstummt sofort. Hältst du weiter, nimmt Penny direkt deine neue Frage auf (nur `PTT_MODE=hold`).
- Sag **"neues Gespräch"**, um Pennys Gedächtnis zu löschen (leert auch die Datei).
- **Ctrl+C** beendet.

Im Terminal wird jeder Turn mitgeloggt:

```
14:02:11 INFO    [1] DU     (0.8s STT): Was bringt ein Glurak ex aus Obsidianflammen gerade?
14:02:13 INFO    [1] PENNY  (0.9s bis zum ersten Ton): Die Special Illustration Rare liegt grob bei ...
```

## Push-to-Talk-Modi

| `PTT_MODE` | Verhalten |
|---|---|
| `hold` (Standard) | Taste gedrückt halten. Nutzt `pynput`, reagiert **global**, also auch wenn das Terminal nicht im Fokus ist. |
| `enter` | Enter startet, Enter stoppt. Nur im Terminal, braucht keinerlei Sonderrechte. |

Hinweise zu `hold`:

- **macOS:** Terminal (bzw. iTerm/VS Code) braucht unter *Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen* und *Eingabeüberwachung* die Freigabe.
- **Linux:** funktioniert unter X11. Unter Wayland liefert `pynput` meist keine Tasten, dann `PTT_MODE=enter` nutzen.
- Weil der Hotkey global ist, startet Q + E auch in anderen Programmen eine Aufnahme, falls du beide gleichzeitig hältst. Beim normalen Tippen passiert das kaum, Aufnahmen unter 0,3 s werden verworfen.
- Andere Taste oder Kombination: `PTT_KEY=f9`, `PTT_KEY=space`, `PTT_KEY=ctrl_r+alt_r` usw. Mehrere Tasten mit `+` verbinden.
- Im Terminal werden gehaltene Tasten nicht mehr als "qeqeqe" angezeigt (macOS/Linux).

## Stimme

| Einstellung | Wirkung |
|---|---|
| `ELEVENLABS_TTS_MODEL=eleven_flash_v2_5` | Standard, schnellste Antwort |
| `TTS_SPEED=1.05` | Sprechtempo 0.7 bis 1.2 |
| `STREAMING=nein` | Erst die komplette Antwort, dann sprechen. Langsamer, nur zur Fehlersuche |
| `BEGRUESSUNG=nein` | Keine Ansage beim Start |

Penny schickt jeden Satz einzeln an ElevenLabs und gibt den vorherigen Satz als Kontext mit, damit die Betonung durchgehend klingt. Den nächsten Satz holt sie schon, während der aktuelle läuft, deshalb gibt es keine Pausen dazwischen. Markdown, Emojis und Gedankenstriche werden vor dem Vorlesen entfernt, `€` und `%` werden zu "Euro" und "Prozent".

## Dashboard

Mit `python main.py` öffnet sich automatisch das Dashboard unter **http://localhost:8765**. Es zeigt nur Penny: ihren animierten Kern, ob sie gerade zuhört, versteht, nachdenkt oder spricht, und als Untertitel deine Frage bzw. ihre Antwort. Die Antwort erscheint live, Wort für Wort, während Penny spricht.

- `python main.py --kein-dashboard` startet Penny ohne Dashboard.
- `python main.py --ohne-claude` zeigt das Dashboard live, ganz ohne API-Guthaben.
- Das Dashboard ist nur auf deinem eigenen Rechner erreichbar (127.0.0.1).
- Einstellungen: `DASHBOARD`, `DASHBOARD_PORT`, `DASHBOARD_OPEN` in der `.env`.

## Gedächtnis

Penny speichert den Verlauf nach jeder Antwort in `penny_gedaechtnis.json` im Projektordner und lädt ihn beim Start wieder. Gemerkt werden die letzten `HISTORY_TURNS` Turns (Standard 10). Mehr Turns bedeuten ein besseres Gedächtnis, kosten aber etwas mehr pro Frage.

- Löschen: "neues Gespräch" sagen oder die Datei löschen.
- Die Datei landet nie im Repo (steht in `.gitignore`).
- Ist die Datei beschädigt, wird sie als `penny_gedaechtnis.defekt.json` gesichert und Penny startet mit leerem Gedächtnis.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `PortAudio library not found` | PortAudio installieren (siehe Installation) |
| Keine Reaktion auf Q + E | macOS-Rechte prüfen, unter Wayland `PTT_MODE=enter` |
| Falsches Mikrofon | `python audio_input.py` zeigt Geräte, dann `INPUT_DEVICE=<Index>` |
| `401` von ElevenLabs | API-Key oder dessen Berechtigungen (TTS/STT) prüfen |
| `404` von ElevenLabs | Voice-ID prüfen |
| Antworten zu lang oder zu förmlich | `system_prompt.txt` anpassen, Neustart genügt |
| Keine Begrüßung zu hören | Lautsprecher/Standard-Ausgabegerät prüfen, dann `python tts_elevenlabs.py` |
| Knacken oder Aussetzer zwischen Sätzen | `STREAMING=nein` testen und mit `--debug` starten, das zeigt die Latenzen |
| Q + E unterbricht nicht | Nur mit `PTT_MODE=hold`. Bei `enter` gibt es keine Unterbrechung |

## Ausbaustufen (noch nicht umgesetzt)

- Wake-Word statt Push-to-Talk (OpenWakeWord) und automatisches Aufnahme-Ende (Silero VAD)
- Tool-Use: Live-Preise (Websuche, TCGdex), Einkaufsliste, Bestandsabfrage
- Langzeitgedächtnis (Hindsight)
