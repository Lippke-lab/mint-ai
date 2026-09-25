from types import SimpleNamespace

from claude_brain import ClaudeBrain, Memory


class FakeStream:
    def __init__(self, parts, stop_reason="end_turn"):
        self.text_stream = iter(parts)
        self._msg = SimpleNamespace(
            stop_reason=stop_reason, stop_details=None,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                  cache_read_input_tokens=50, cache_creation_input_tokens=None))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._msg


class FakeClient:
    def __init__(self, *streams):
        self.streams = list(streams)
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self.streams.pop(0)


def make_brain(tmp_path, *streams):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Du bist Penny.", encoding="utf-8")
    brain = ClaudeBrain("key", "claude-sonnet-5", prompt, history_turns=2,
                        memory=Memory(tmp_path / "mem.json"))
    brain.client = FakeClient(*streams)
    return brain


def test_stream_yields_parts_and_saves_history(tmp_path):
    brain = make_brain(tmp_path, FakeStream(["Hallo ", "Chef."]))
    assert list(brain.ask_stream("Hi")) == ["Hallo ", "Chef."]
    assert brain.history[-1] == {"role": "assistant", "content": "Hallo Chef."}
    assert brain.last_usage == {"input": 100, "output": 20, "cache_read": 50, "cache_write": 0}
    assert Memory(tmp_path / "mem.json").load() == brain.history
    call = brain.client.calls[0]
    assert call["cache_control"] == {"type": "ephemeral"}
    assert call["messages"][-1] == {"role": "user", "content": "Hi"}


def test_refusal_is_not_remembered(tmp_path):
    brain = make_brain(tmp_path, FakeStream(["Ok."]), FakeStream([], stop_reason="refusal"))
    brain.ask("Erste Frage")
    before = list(brain.history)
    assert brain.ask("Böse Frage") == "Dazu kann ich leider nichts sagen."
    assert brain.history == before


def test_empty_answer_gets_fallback(tmp_path):
    brain = make_brain(tmp_path, FakeStream([]))
    assert "nichts eingefallen" in brain.ask("Hm?")


def test_history_is_trimmed(tmp_path):
    brain = make_brain(tmp_path, *[FakeStream([f"A{i}"]) for i in range(3)])
    for i in range(3):
        brain.ask(f"F{i}")
    assert [m["content"] for m in brain.history] == ["F1", "A1", "F2", "A2"]
