"""ChatInput — the text input bar."""

from __future__ import annotations

from textual.widgets import Input

# Detect whether sounddevice is importable just so the status bar can hint
# at simulation vs real mic. The actual capture lives in src/asr/.
try:
    import sounddevice  # noqa: F401

    AUDIO_AVAILABLE = True
except Exception:  # pragma: no cover
    AUDIO_AVAILABLE = False


class ChatInput(Input):
    DEFAULT_CSS = """
    ChatInput {
        margin: 0 1;
        border: round $primary;
    }
    ChatInput:focus { border: round $accent; }
    """

    DEFAULT_PLACEHOLDER = (
        "Type a message or /command (try /help, /cost, /schedules)…"
    )

    def __init__(self) -> None:
        super().__init__(placeholder=self.DEFAULT_PLACEHOLDER, id="chat-input")
