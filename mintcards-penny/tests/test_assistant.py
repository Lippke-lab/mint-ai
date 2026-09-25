import threading

from assistant import Penny
from claude_brain import EchoBrain


class FakeVoice:
    def __init__(self):
        self.spoken = []

    def speak_stream(self, deltas, stop=None, on_text=None, on_audio_start=None):
        text = "".join(deltas)
        if on_text:
            on_text(text)
        if on_audio_start:
            on_audio_start()
        self.spoken.append(text)
        return text, False

    def say(self, text, stop=None, on_audio_start=None):
        self.spoken.append(text)
        return True


class UsageBrain(EchoBrain):
    def __init__(self):
        self.last_usage = {"input": 1_000_000, "output": 100_000, "cache_read": 1_000_000,
                           "cache_write": 0}


def test_respond_streams_and_records_turn():
    voice = FakeVoice()
    penny = Penny(EchoBrain(), voice, info={"modell": "x"})
    events = penny.events.subscribe()
    assert penny.respond("Wie geht's?") == "Verstanden: Wie geht's?"
    assert voice.spoken == ["Verstanden: Wie geht's?"]
    turn = penny.turns[-1]
    assert turn["unterbrochen"] is False and "erster_ton" in turn["dauer"]
    kinds = [events.get_nowait()[0] for _ in range(events.qsize())]
    assert "teil" in kinds and "turn" in kinds
    assert penny.state == "bereit"


def test_reset_command_speaks_confirmation():
    voice = FakeVoice()
    penny = Penny(EchoBrain(), voice)
    assert penny.respond("Neues Gespräch.") == "Erledigt. Wir fangen von vorne an."
    assert voice.spoken == ["Erledigt. Wir fangen von vorne an."]


def test_cost_includes_cache_tokens():
    penny = Penny(UsageBrain(), None, info={"modell": "claude-sonnet-5"})
    penny.respond("x", speak=False)
    # 1M Eingabe à 2 $ + 0,1M Ausgabe à 10 $ + 1M Cache-Lesen à 0,20 $
    assert penny.stats["kosten_usd"] == 3.2


def test_interrupt_only_while_busy():
    penny = Penny(EchoBrain(), FakeVoice())
    penny.interrupt()
    assert not penny._interrupt.is_set()
    penny._busy = True
    penny.interrupt()
    assert penny._interrupt.is_set()


def test_voice_can_be_interrupted_from_other_thread():
    stop_seen = threading.Event()

    class SlowVoice(FakeVoice):
        def speak_stream(self, deltas, stop=None, on_text=None, on_audio_start=None):
            text = "".join(deltas)
            stop_seen.set()
            assert stop.wait(2)
            return text, True

    penny = Penny(EchoBrain(), SlowVoice())
    t = threading.Thread(target=lambda: (stop_seen.wait(2), penny.interrupt()))
    t.start()
    penny.respond("Erzähl was")
    t.join()
    assert penny.turns[-1]["unterbrochen"] is True
