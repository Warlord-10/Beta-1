"""Beta-1 TUI — the Textual app.

Thin orchestrator: wires Pipeline callbacks to the chat view, the input bar,
and the various tab panes. State lives in the widgets; this class just
plumbs events.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Static, TabbedContent, TabPane

from .panes import (
    CostsPane,
    DatabasePane,
    EditorPane,
    SchedulesPane,
    SettingsPane,
)
from .widgets import AUDIO_AVAILABLE, ChatInput, ChatView, PlanReview

if TYPE_CHECKING:
    from src.pipeline import Pipeline


class TUI(App):
    """Textual chat GUI bound to the chat pipeline."""

    TITLE = "Beta-1"
    SUB_TITLE = "Personal AI Assistant"

    TAB_IDS = ("chat", "settings", "schedules", "costs", "database", "editor")

    CSS = """
    Screen { background: $surface; }
    #main-tabs { height: 1fr; }
    TabbedContent Tabs { background: $panel; }
    #bottom-area {
        height: auto;
        dock: bottom;
        background: $surface;
    }
    #status-bar {
        height: 1;
        background: $panel;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "toggle_live", "Live", show=True),
        Binding("ctrl+k", "clear_chat", "Clear", show=True),
        Binding("ctrl+d", "toggle_dark", "Theme", show=True),
    ]

    def __init__(self, pipeline: Optional["Pipeline"] = None) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._chat_view = ChatView()
        self._chat_input = ChatInput()
        self._plan_review = PlanReview()

    # ── layout ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="chat", id="main-tabs"):
            with TabPane("💬 Chat", id="chat"):
                yield self._chat_view
            with TabPane("⚙️ Settings", id="settings"):
                yield SettingsPane()
            with TabPane("📅 Schedules", id="schedules"):
                yield SchedulesPane()
            with TabPane("💰 Costs", id="costs"):
                yield CostsPane()
            with TabPane("🗄️ Database", id="database"):
                yield DatabasePane()
            with TabPane("📝 Editor", id="editor"):
                yield EditorPane()
        with Container(id="bottom-area"):
            yield Static(self._status_text(), id="status-bar", markup=True)
            yield self._chat_input

    def on_mount(self) -> None:
        self._chat_input.focus()
        self._chat_view.post_bot(
            "[bold cyan]Beta-1[/] ready. "
            "[dim]Personal AI Assistant • by Deepanshu Joshi[/]"
        )
        if self._pipeline is not None:
            self._pipeline.attach_output(
                on_chunk=self._on_chunk,
                on_turn_start=self._on_turn_start,
                on_turn_end=self._on_turn_end,
                on_thinking=self._on_thinking,
            )
            self._pipeline.attach_user_input_listener(self._on_user_msg)
            self._pipeline.attach_plan_review_listener(self._on_plan_review)

        self.set_interval(30.0, self._refresh_live_tabs)

    # ── pipeline callbacks (worker threads) ─────────────────────────────
    def _on_turn_start(self) -> None:
        self.call_from_thread(self._chat_view.start_bot_turn)

    def _on_chunk(self, chunk: str) -> None:
        self.call_from_thread(self._chat_view.append_bot, chunk)
        self.call_from_thread(self._refresh_status)

    def _on_turn_end(self) -> None:
        self.call_from_thread(self._chat_view.end_bot_turn)
        self.call_from_thread(self._refresh_status)

    def _on_thinking(self, chunk: str) -> None:
        self.call_from_thread(self._chat_view.append_thinking, chunk)

    def _on_user_msg(self, text: str) -> None:
        self.call_from_thread(self._chat_view.post_user, text)
        self.call_from_thread(self._refresh_status)

    def _on_plan_review(self, plan: dict) -> None:
        self.call_from_thread(self._show_plan_review, plan)

    def _show_plan_review(self, plan: dict) -> None:
        self._plan_review.request(plan)
        self._chat_view.post_bot(PlanReview.render(plan))
        self._refresh_status()

    # ── input ───────────────────────────────────────────────────────────
    @on(ChatInput.Submitted, "#chat-input")
    def on_input_submit(self, event: ChatInput.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
            return

        self._chat_view.post_user(text)

        if self._plan_review.awaiting and self._pipeline is not None:
            # Anything that isn't a verdict is treated as a revised plan.
            self._pipeline.submit_plan_review(text)
            self._plan_review.resolve()
            self._chat_view.post_bot("[yellow]Plan revision submitted.[/]")
            self._refresh_status()
            return

        if self._pipeline is None:
            self._chat_view.post_bot("[red]No pipeline attached.[/]")
            return
        self._pipeline.submit(text)
        self._refresh_status()

    # ── commands ────────────────────────────────────────────────────────
    def _handle_command(self, raw: str) -> None:
        parts = raw[1:].strip().split()
        if not parts:
            return
        cmd = parts[0].lower()

        if cmd == "approve" and self._plan_review.awaiting:
            self._submit_verdict("approve", "✅ Plan approved.")
        elif cmd == "reject" and self._plan_review.awaiting:
            self._submit_verdict("reject", "🛑 Plan rejected.")
        elif cmd in self.TAB_IDS:
            self.query_one(TabbedContent).active = cmd
            self._chat_view.post_bot(f"📂 Switched to the [b]{cmd}[/] tab.")
        elif cmd == "live":
            self.action_toggle_live()
        elif cmd == "help":
            self._chat_view.post_bot(self._help_text())
        elif cmd == "clear":
            self.action_clear_chat()
        elif cmd in ("quit", "exit"):
            self.exit()
        elif cmd == "theme":
            self.action_toggle_dark()
        elif cmd == "cost":
            self.query_one(TabbedContent).active = "costs"
            self._refresh_pane(CostsPane)
        else:
            self._chat_view.post_bot(
                f"❓ Unknown command: [b]/{cmd}[/]. Try [b]/help[/]."
            )

    def _submit_verdict(self, verdict: str, ack: str) -> None:
        if self._pipeline is not None:
            self._pipeline.submit_plan_review(verdict)
        self._plan_review.resolve()
        self._chat_view.post_bot(ack)
        self._refresh_status()

    @staticmethod
    def _help_text() -> str:
        return (
            "📖 [bold]Available commands[/]\n\n"
            "  [b]/chat[/]       Open the chat tab\n"
            "  [b]/settings[/]   Open settings\n"
            "  [b]/schedules[/]  Open your schedules\n"
            "  [b]/costs[/]      Open the cost tab\n"
            "  [b]/database[/]   Open the live SQL tab\n"
            "  [b]/editor[/]     Open the file editor tab\n"
            "  [b]/live[/]       Toggle live audio mode (Ctrl+L)\n"
            "  [b]/clear[/]      Clear the conversation (Ctrl+K)\n"
            "  [b]/theme[/]      Toggle dark/light theme (Ctrl+D)\n"
            "  [b]/approve[/]    Approve the current plan (when prompted)\n"
            "  [b]/reject[/]     Reject the current plan (when prompted)\n"
            "  [b]/help[/]       Show this help\n"
            "  [b]/quit[/]       Exit (Ctrl+C)"
        )

    # ── status bar ──────────────────────────────────────────────────────
    def _status_text(self) -> str:
        live = (
            "[bold red]● LIVE[/]" if self._chat_input.live else "[dim]○ idle[/]"
        )
        audio_src = "mic" if AUDIO_AVAILABLE else "sim"
        plan_hint = (
            "  │  [yellow]📋 awaiting plan review[/]"
            if self._plan_review.awaiting else ""
        )
        return (
            f"  {live}  │  💬 {self._chat_view.message_count} messages  │  "
            f"🎛 audio:{audio_src}{plan_hint}  │  "
            f"[dim]Ctrl+L live · Ctrl+K clear · Ctrl+D theme · Ctrl+C quit[/]"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:
            pass

    # ── tab refresh ─────────────────────────────────────────────────────
    def _refresh_live_tabs(self) -> None:
        self._refresh_pane(SchedulesPane)
        self._refresh_pane(CostsPane)
        self._refresh_pane(DatabasePane)

    def _refresh_pane(self, pane_cls) -> None:
        try:
            self.query_one(pane_cls).refresh_data()
        except Exception:
            pass

    @on(TabbedContent.TabActivated)
    def _on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        active = event.tab.id or ""
        if active.endswith("schedules"):
            self._refresh_pane(SchedulesPane)
        elif active.endswith("costs"):
            self._refresh_pane(CostsPane)
        elif active.endswith("database"):
            self._refresh_pane(DatabasePane)
        elif active.endswith("chat"):
            # Return focus to the input so the user can keep typing without
            # an extra click — fixes "no interaction after switching tabs".
            self._chat_input.focus()

    # ── actions ─────────────────────────────────────────────────────────
    def action_toggle_live(self) -> None:
        if self._chat_input.live:
            self._chat_input.exit_live_mode()
            self._chat_view.post_bot("🔇 Live mode off.")
        else:
            self._chat_input.enter_live_mode()
            if AUDIO_AVAILABLE:
                self._chat_view.post_bot(
                    "🎤 Live mode on — speak into your microphone."
                )
            else:
                self._chat_view.post_bot(
                    "🎤 Live mode on (no microphone detected — install "
                    "[b]sounddevice[/] for real input)."
                )
        self._refresh_status()

    def action_clear_chat(self) -> None:
        self._chat_view.clear()
        self._chat_view.post_bot("🧹 Chat cleared.")
        self._refresh_status()

    def action_toggle_dark(self) -> None:
        try:
            self.theme = (
                "textual-light" if self.theme == "textual-dark" else "textual-dark"
            )
        except Exception:
            try:
                self.dark = not self.dark
            except Exception:
                pass
        self._chat_view.post_bot("🎨 Theme toggled.")
