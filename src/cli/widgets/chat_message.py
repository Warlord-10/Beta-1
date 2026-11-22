"""A single chat row: user or bot."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class ChatMessage(Horizontal):
    """A single terminal-style chat line."""

    KIND_USER = "user"
    KIND_BOT = "bot"
    KIND_TOOL = "tool"

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    ChatMessage > .bubble {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0;
    }
    ChatMessage.-user > .bubble { color: $success; }
    ChatMessage.-bot   > .bubble { color: $text; }
    ChatMessage.-tool  > .bubble {
        width: auto;
        color: dodgerblue;
        border: round lightskyblue;
        padding: 0 1;
    }
    """

    _PREFIX = {
        KIND_USER:     "[bold green]❯[/]",
        KIND_BOT:      "[bold cyan]✦[/]",
        KIND_TOOL:     "🔧",
    }

    def __init__(self, text: str = "", *, kind: str = KIND_BOT) -> None:
        super().__init__()
        self._kind = kind
        self._ts = datetime.now().strftime("%H:%M")
        self._text = text
        self.add_class(f"-{kind}")
        self._static: Optional[Static] = None

    # ── factories ────────────────────────────────────────────────────────
    @classmethod
    def user(cls, text: str = "") -> "ChatMessage":
        return cls(text, kind=cls.KIND_USER)

    @classmethod
    def bot(cls, text: str = "") -> "ChatMessage":
        return cls(text, kind=cls.KIND_BOT)

    @classmethod
    def tool(cls, text: str) -> "ChatMessage":
        return cls(text, kind=cls.KIND_TOOL)

    @property
    def text(self) -> str:
        return self._text

    # ── render ───────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        self._static = Static(self._bubble_text(), classes="bubble", markup=True)
        yield self._static

    def _bubble_text(self) -> str:
        if self._kind == self.KIND_TOOL:
            return f"{self._PREFIX[self._kind]} {self._text}"
        return f"[dim]{self._ts}[/dim] {self._PREFIX[self._kind]} {self._text}"

    # ── mutation ─────────────────────────────────────────────────────────
    def append(self, chunk: str) -> None:
        self._text += chunk
        if self._static is not None:
            self._static.update(self._bubble_text())
