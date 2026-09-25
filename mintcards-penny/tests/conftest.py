"""Gemeinsame Test-Helfer: Projektordner importierbar, sounddevice notfalls als Attrappe."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # ohne PortAudio (CI, Server) wirft der Import OSError
    import sounddevice  # noqa: F401
except OSError:
    sys.modules["sounddevice"] = types.SimpleNamespace(
        InputStream=None, RawOutputStream=None, play=None, wait=None, stop=None)
