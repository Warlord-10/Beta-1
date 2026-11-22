"""VoiceMeter — a row of bars above the input showing who is talking.

Red bouncing bars while the user speaks (VAD), blue while the bot speaks
(speaker playing), flat dim bars otherwise.
"""

from __future__ import annotations

import random
from typing import Callable

from textual.widgets import Static

from src.config.global_events import CheckUserBargeIn

_LEVELS = " ▁▂▃▄▅▆▇█"
_BARS = 32


class VoiceMeter(Static):
    DEFAULT_CSS = """
    VoiceMeter {
        height: 1;
        width: auto;
    }
    """

    def __init__(self, bot_speaking: Callable[[], bool] = lambda: False) -> None:
        super().__init__(id="voice-meter")
        self._bot_speaking = bot_speaking
        self._heights = [1] * _BARS

    def on_mount(self) -> None:
        self.set_interval(1 / 12, self._redraw)

    # Not `_animate`: Textual uses that name internally and sets it to None.
    def _redraw(self) -> None:
        if CheckUserBargeIn():
            color = "bold red"
        elif self._bot_speaking():
            color = "bold #1e90ff"
        else:
            color = "dim"
        # ponytail: random heights gated by who is talking, not the real audio
        # level. Publish block RMS from ASR/TTS if it should track volume.
        for i, h in enumerate(self._heights):
            target = random.randint(2, 8) if color != "dim" else 1
            self._heights[i] = (h + target) // 2  # ease toward target
        bars = " ".join(_LEVELS[h] for h in self._heights)
        self.update(f"[{color}]{bars}[/]")
