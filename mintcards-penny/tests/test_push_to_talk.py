from types import SimpleNamespace

from audio_input import PushToTalk


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.starts = 0

    def start(self):
        self.is_recording = True
        self.starts += 1

    def stop(self):
        self.is_recording = False
        return b"wav"


def make_ptt():
    ptt = PushToTalk(FakeRecorder(), mode="enter")  # "enter" braucht kein pynput/Display
    ptt._combo = frozenset({"q", "e"})
    return ptt


def key(c):
    return SimpleNamespace(char=c)


def test_combo_while_busy_interrupts_instead_of_recording():
    ptt = make_ptt()
    hits = []
    ptt.on_interrupt = lambda: hits.append(1)
    ptt._on_press(key("q"))
    assert hits == []
    ptt._on_press(key("e"))
    assert hits == [1]
    assert ptt.recorder.starts == 0


def test_held_combo_starts_recording_when_armed():
    ptt = make_ptt()
    ptt._on_press(key("q"))
    ptt._on_press(key("e"))  # Barge-in, Penny spricht noch
    ptt._armed.set()
    ptt._begin()
    ptt._on_press(key("e"))  # Autorepeat
    assert ptt.recorder.starts == 1
    ptt._on_release(key("e"))
    assert ptt._result == b"wav" and ptt._done.is_set()
