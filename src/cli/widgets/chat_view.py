"""ChatView — the scrolling chat pane plus its streaming-bubble state.

The TUI feeds events here from the pipeline worker threads (via
`call_from_thread`). The view owns the active bot bubble, so the
TUI app stays small and the streaming logic is testable in isolation.

All public methods are safe to call when the chat tab is not currently
visible — Textual keeps inactive tab panes mounted, but we still guard
each widget access in case the user navigates while we are streaming.
"""

from __future__ import annotations

from typing import Optional

from rich.markup import escape

from textual.app import ComposeResult
from textual.containers import VerticalScroll

from .chat_message import ChatMessage


_MAX_ARGS = 80


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
        self._message_count = 0

    def compose(self) -> ComposeResult:
        return iter(())  # rows are mounted dynamically

    # ── posting completed lines ──────────────────────────────────────────
    # User and LLM text is escaped: a "[1]" or "[/]" in it is not markup.
    # post_bot takes markup: it is for the app's own messages.
    def post_user(self, text: str) -> None:
        self._mount(ChatMessage.user(escape(text)))

    def post_bot(self, text: str) -> None:
        self._mount(ChatMessage.bot(text))

    def post_tool(self, name: str, args: dict) -> None:
        """A tool call the bot made. Splits the bot turn: text after the
        call goes in a new bubble below it."""
        bubble = self._active_bot
        if bubble is not None:
            if bubble.text:
                self._message_count += 1
            else:
                bubble.remove()  # nothing said yet: drop the empty bubble
            self._active_bot = None
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        if len(shown) > _MAX_ARGS:
            shown = shown[: _MAX_ARGS - 1] + "…"
        self._mount(ChatMessage.tool(f"[b]{escape(name)}[/b]({escape(shown)})"), count=False)

    # ── streaming a bot turn ─────────────────────────────────────────────
    def start_bot_turn(self) -> None:
        self._active_bot = ChatMessage.bot("")
        self._mount(self._active_bot, count=False)

    def append_bot(self, chunk: str) -> None:
        if self._active_bot is None or not self._active_bot.is_mounted:
            self.start_bot_turn()
        assert self._active_bot is not None
        try:
            self._active_bot.append(escape(chunk))
            self.scroll_end(animate=False)
        except Exception:
            # widget may have been removed during a /clear or unmount
            self._active_bot = None

    def end_bot_turn(self) -> None:
        if self._active_bot is not None:
            self._message_count += 1
        self._active_bot = None

    # ── housekeeping ─────────────────────────────────────────────────────
    def clear(self) -> None:
        for child in list(self.children):
            child.remove()
        self._active_bot = None
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
