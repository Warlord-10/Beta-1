"""ChatInput — the text input bar with live-mode visuals.

In live mode the border turns thick red, a "LIVE MODE" title appears, and a
small mic-activity indicator animates in the bottom-right of the border —
brighter and faster while the user is actively speaking (driven by
`GlobalEvents.is_user_speaking`).
"""

from __future__ import annotations

from typing import Optional

from textual.timer import Timer
from textual.widgets import Input

# Detect whether sounddevice is importable just so the status bar can hint
# at simulation vs real mic. The actual capture lives in src/asr/.
try:
    import sounddevice  # noqa: F401

    AUDIO_AVAILABLE = True
except Exception:  # pragma: no cover
    AUDIO_AVAILABLE = False


# Frames cycled in the border title to suggest activity.
_IDLE_FRAMES = ("●", "◉", "○", "◉")          # gentle pulse when listening but silent
_ACTIVE_FRAMES = ("▁", "▃", "▅", "▇", "▅", "▃")  # taller bars while speech detected


class ChatInput(Input):
    """Input widget that knows how to enter/leave live mode."""

    DEFAULT_CSS = """
    ChatInput {
        margin: 0 1;
        border: round $primary;
    }
    ChatInput:focus { border: round $accent; }
    ChatInput.-live { border: thick red; }
    """

    DEFAULT_PLACEHOLDER = (
        "Type a message or /command (try /help, /cost, /schedules)…"
    )

    def __init__(self) -> None:
        super().__init__(placeholder=self.DEFAULT_PLACEHOLDER, id="chat-input")
        self._live = False
        self._frame = 0
        self._tick: Optional[Timer] = None

    # ── mode toggle ─────────────────────────────────────────────────────
    def enter_live_mode(self) -> None:
        if self._live:
            return
        self._live = True
        self.add_class("-live")
        self.border_title = self._title_for(speaking=False)
        # 8 Hz animation — fast enough to feel alive, cheap enough to ignore.
        self._tick = self.set_interval(0.125, self._animate)

    def exit_live_mode(self) -> None:
        if not self._live:
            return
        self._live = False
        self.remove_class("-live")
        self.border_title = ""
        if self._tick is not None:
            self._tick.stop()
            self._tick = None

    @property
    def live(self) -> bool:
        return self._live

    # ── animation ───────────────────────────────────────────────────────
    def _animate(self) -> None:
        # Imported lazily so this widget stays usable in tests without the
        # global-events module being initialised.
        try:
            from src.config.events import GlobalEvents

            speaking = GlobalEvents.CheckUserBargeIn()
        except Exception:
            speaking = False
        self._frame += 1
        self.border_title = self._title_for(speaking=speaking)

    def _title_for(self, *, speaking: bool) -> str:
        if speaking:
            frame = _ACTIVE_FRAMES[self._frame % len(_ACTIVE_FRAMES)]
            return f"[b white on red] LIVE MODE  🎤 {frame} [/]"
        frame = _IDLE_FRAMES[self._frame % len(_IDLE_FRAMES)]
        # Dim grey for "listening, no voice yet" so it's clearly inactive.
        return f"[b white on red] LIVE MODE [/][dim red on default]  {frame}[/]"
