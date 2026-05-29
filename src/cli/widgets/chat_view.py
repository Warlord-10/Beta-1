"""ChatView — the scrolling chat pane plus its streaming-bubble state.

The TUI feeds events here from the pipeline worker threads (via
`call_from_thread`). The view owns the active bot/thinking bubbles, so the
TUI app stays small and the streaming logic is testable in isolation.

All public methods are safe to call when the chat tab is not currently
visible — Textual keeps inactive tab panes mounted, but we still guard
each widget access in case the user navigates while we are streaming.
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll

from .chat_message import ChatMessage


class ChatView(VerticalScroll):
    """Owns the chat transcript and the in-flight streaming bubbles."""

    DEFAULT_CSS = """
    ChatView {
        padding: 0 1;
        height: 1fr;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._active_bot: Optional[ChatMessage] = None
        self._active_thinking: Optional[ChatMessage] = None
        self._message_count = 0

    def compose(self) -> ComposeResult:
        return iter(())  # rows are mounted dynamically

    # ── posting completed lines ──────────────────────────────────────────
    def post_user(self, text: str) -> None:
        self._mount(ChatMessage.user(text))

    def post_bot(self, text: str) -> None:
        self._mount(ChatMessage.bot(text))

    # ── streaming a bot turn ─────────────────────────────────────────────
    def start_bot_turn(self) -> None:
        self._active_thinking = None
        self._active_bot = ChatMessage.bot("")
        self._mount(self._active_bot, count=False)

    def append_bot(self, chunk: str) -> None:
        if self._active_bot is None or not self._active_bot.is_mounted:
            self.start_bot_turn()
        assert self._active_bot is not None
        try:
            self._active_bot.append(chunk)
            self.scroll_end(animate=False)
        except Exception:
            # widget may have been removed during a /clear or unmount
            self._active_bot = None

    def end_bot_turn(self) -> None:
        if self._active_bot is not None:
            self._message_count += 1
        self._active_bot = None
        self._active_thinking = None

    # ── streaming model thinking ─────────────────────────────────────────
    def append_thinking(self, chunk: str) -> None:
        if self._active_thinking is None or not self._active_thinking.is_mounted:
            self._active_thinking = ChatMessage.thinking("")
            self._mount(self._active_thinking, count=False)
        try:
            self._active_thinking.append(chunk)
            self.scroll_end(animate=False)
        except Exception:
            self._active_thinking = None

    # ── housekeeping ─────────────────────────────────────────────────────
    def clear(self) -> None:
        for child in list(self.children):
            child.remove()
        self._active_bot = None
        self._active_thinking = None
        self._message_count = 0

    @property
    def message_count(self) -> int:
        return self._message_count

    # ── internal ─────────────────────────────────────────────────────────
    def _mount(self, msg: ChatMessage, *, count: bool = True) -> None:
        try:
            self.mount(msg)
            self.scroll_end(animate=False)
            if count:
                self._message_count += 1
        except Exception:
            # Mounting can race with tab teardown; safe to drop.
            pass
