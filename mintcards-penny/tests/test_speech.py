import threading
import time

import pytest

from speech import BufferPlayer, SentenceSplitter, SpeechOutput, clean_for_speech


def split_all(text: str, step: int = 3) -> list[str]:
    s = SentenceSplitter()
    out = []
    for i in range(0, len(text), step):
        out += s.feed(text[i:i + step])
    return out + s.flush()


def test_splits_sentences_while_streaming():
    text = "Die Karte liegt bei etwa 45 Euro. Für schnellen Verkauf eher 40! Willst du sie listen?"
    assert split_all(text) == [
        "Die Karte liegt bei etwa 45 Euro.",
        "Für schnellen Verkauf eher 40!",
        "Willst du sie listen?",
    ]


def test_first_sentence_is_emitted_before_the_answer_is_complete():
    s = SentenceSplitter()
    assert s.feed("Systeme sind online. Und dann") == ["Systeme sind online."]


def test_abbreviations_and_ordinals_do_not_end_a_sentence():
    text = "Das kostet z. B. bei Cardmarket ca. 30 Euro. Am 3. Mai kommt das neue Set."
    assert split_all(text) == [
        "Das kostet z. B. bei Cardmarket ca. 30 Euro.",
        "Am 3. Mai kommt das neue Set.",
    ]


def test_decimal_numbers_stay_together():
    assert split_all("Der Preis ist um 2.5 Prozent gestiegen. Gut so.") == [
        "Der Preis ist um 2.5 Prozent gestiegen.", "Gut so."]


def test_short_fragments_are_merged():
    assert split_all("Klar. Das Display lohnt sich noch.") == ["Klar. Das Display lohnt sich noch."]


def test_clean_for_speech():
    assert clean_for_speech("**Glurak** kostet 45 € – super 🔥") == "Glurak kostet 45 Euro, super"
    assert clean_for_speech("- Punkt eins\n- Punkt zwei") == "Punkt eins Punkt zwei"
    assert clean_for_speech("Plus 12% & mehr") == "Plus 12 Prozent und mehr"


class FakeTTS:
    def __init__(self, delay: float = 0.0, fail_on: str | None = None):
        self.calls: list[tuple[str, str | None]] = []
        self.delay = delay
        self.fail_on = fail_on

    def stream_pcm(self, text, previous_text=None):
        self.calls.append((text, previous_text))
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("TTS kaputt")
        for _ in range(3):
            time.sleep(self.delay)
            yield text.encode()[:4].ljust(4, b"_")


def test_pipeline_speaks_all_sentences_in_order_with_context():
    tts, player = FakeTTS(), BufferPlayer()
    started = []
    text, interrupted = SpeechOutput(tts, lambda: player).speak_stream(
        ["Erster Satz ist da. ", "Zweiter Satz", " folgt jetzt."], on_audio_start=lambda: started.append(1))
    assert text == "Erster Satz ist da. Zweiter Satz folgt jetzt."
    assert not interrupted
    assert [c[0] for c in tts.calls] == ["Erster Satz ist da.", "Zweiter Satz folgt jetzt."]
    assert tts.calls[0][1] is None and tts.calls[1][1] == "Erster Satz ist da."
    assert bytes(player.data) == b"Erst" * 3 + b"Zwei" * 3
    assert started == [1]


def test_on_text_reports_growing_text():
    seen = []
    SpeechOutput(FakeTTS(), BufferPlayer).speak_stream(["Hallo ", "Chef, alles ", "bereit."],
                                                       on_text=seen.append)
    assert seen == ["Hallo ", "Hallo Chef, alles ", "Hallo Chef, alles bereit."]


def test_interrupt_stops_audio_but_reads_full_text():
    tts, player = FakeTTS(delay=0.05), BufferPlayer()
    stop = threading.Event()
    timer = threading.Timer(0.08, stop.set)
    timer.start()
    text, interrupted = SpeechOutput(tts, lambda: player).speak_stream(
        ["Satz eins ist lang genug. ", "Satz zwei ist auch lang. ", "Satz drei ebenso lang."], stop)
    timer.cancel()
    assert interrupted
    assert player.aborted
    assert text.endswith("Satz drei ebenso lang.")  # Gedächtnis bekommt trotzdem alles
    assert len(tts.calls) < 3


def test_tts_errors_are_raised_in_caller():
    with pytest.raises(RuntimeError, match="TTS kaputt"):
        SpeechOutput(FakeTTS(fail_on="zwei"), BufferPlayer).speak_stream(
            ["Satz eins ist lang genug. Satz zwei knallt gleich."])


def test_brain_errors_stop_the_voice():
    player = BufferPlayer()

    def deltas():
        yield "Ein ganzer Satz vorweg. "
        raise ConnectionError("Netz weg")

    with pytest.raises(ConnectionError):
        SpeechOutput(FakeTTS(delay=0.05), lambda: player).speak_stream(deltas())


def test_say_returns_false_when_interrupted():
    stop = threading.Event()
    stop.set()
    assert SpeechOutput(FakeTTS(), BufferPlayer).say("Ein kurzer Test.", stop) is False
