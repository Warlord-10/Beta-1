"""Beta-1 TUI — the Textual app.

Thin orchestrator: subscribes to the pipeline's event bus, marshals events
onto the Textual loop, and drives the tab panes. State lives in the widgets;
the app class just plumbs events between threads. Commands (submit, plan
review, audio toggle) go back to the pipeline via its command API.
"""

from __future__ import annotations

import threading
from typing import Optional, TYPE_CHECKING

from rich.markup import escape
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Static, TabbedContent, TabPane

from src.config.event_bus import (
    EVENT_BUS,
    Chunk,
    PlanReview as PlanReviewEvent,
    TurnEnd,
    TurnStart,
    UserMessage,
    UserQuestion,
    WorkflowStatus,
)
from src.config.global_events import IsWorkflowActive

from .panes import (
    CostsPane,
    DatabasePane,
    EditorPane,
    SchedulesPane,
    SettingsPane,
)
from .widgets import AUDIO_AVAILABLE, ChatInput, ChatView, PlanReview

if TYPE_CHECKING:
    from src.pipeline import AsyncPipeline


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

    def __init__(self, pipeline: Optional["AsyncPipeline"] = None) -> None:
        super().__init__()
        self._pipeline = pipeline
        self.chat_view = ChatView()
        self.chat_input = ChatInput()
        self._plan_review = PlanReview()
        self._question_pending = False

    # ── layout ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="chat", id="main-tabs"):
            with TabPane("💬 Chat", id="chat"):
                yield self.chat_view
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
            yield self.chat_input

    def on_mount(self) -> None:
        self._ui_thread = threading.get_ident()
        self.chat_input.focus()
        self.chat_view.post_bot(
            "[bold cyan]Beta-1[/] ready. "
            "[dim]Personal AI Assistant • by Deepanshu Joshi[/]"
        )
        self._unsubscribe = EVENT_BUS.subscribe(self._on_event)
        self.set_interval(30.0, self._refresh_live_tabs)
        # Cheap status refresh so the workflow-active / live indicators stay
        # in sync without the chat agent needing to fire a callback.
        self.set_interval(1.0, self.refresh_status)

    def on_unmount(self) -> None:
        unsub = getattr(self, "_unsubscribe", None)
        if unsub:
            unsub()

    # ── event bus subscriber ────────────────────────────────────────────
    def _on_event(self, event) -> None:
        """Runs on the shared async loop (chat agent) or on a worker thread
        (ASR) — every UI mutation goes through _ui."""
        if isinstance(event, TurnStart):
            self._ui(self.chat_view.start_bot_turn)
        elif isinstance(event, Chunk):
            self._ui(self.chat_view.append_bot, event.text)
            self._ui(self.refresh_status)
        elif isinstance(event, TurnEnd):
            self._ui(self.chat_view.end_bot_turn)
            self._ui(self.refresh_status)
        elif isinstance(event, UserMessage):
            self._question_pending = False
            self._ui(self.chat_view.post_user, event.text)
            self._ui(self.refresh_status)
        elif isinstance(event, UserQuestion):
            self._ui(self.show_question, event)
        elif isinstance(event, PlanReviewEvent):
            self._ui(self.show_plan_review, event.plan)
        elif isinstance(event, WorkflowStatus):
            self._ui(self._on_workflow_status, event)

    def _ui(self, fn, *args) -> None:
        # Same thread as Textual (events from the async chat loop): call
        # directly — call_from_thread raises there. Other threads: marshal.
        if threading.get_ident() == self._ui_thread:
            fn(*args)
        else:
            self.call_from_thread(fn, *args)

    def _on_workflow_status(self, event) -> None:
        # Post only on status transitions — the bus fires on every plan/file
        # tick, so dedupe to avoid spamming the chat view. Live step-by-step
        # progress is available on demand via the get_workflow_status tool.
        if getattr(self, "_last_wf_status", None) == event.status:
            return
        self._last_wf_status = event.status
        icon = {"running": "⚙", "done": "✅", "failed": "❌",
                "cancelled": "🛑"}.get(event.status, "•")
        if event.status == "running":
            self.chat_view.post_bot(f"{icon} Background task started: [b]{event.task}[/]")
        else:
            files = ", ".join(event.files_changed) or "none"
            self.chat_view.post_bot(
                f"{icon} Background task {event.status}: [b]{event.task}[/]\n"
                f"[dim]Files changed: {files}[/]"
            )
        self.refresh_status()

    # ── plan review entry point ─────────────────────────────────────────
    def show_plan_review(self, plan: dict) -> None:
        self._plan_review.request(plan)
        self.chat_view.post_bot(PlanReview.render(plan))
        self.refresh_status()

    # ── beta-large question entry point ─────────────────────────────────
    def show_question(self, event: UserQuestion) -> None:
        """The pipeline routes the next message to beta-large as the answer."""
        self._question_pending = True
        options = "\n".join(
            f"  [b]{n}.[/] {escape(opt)}" for n, opt in enumerate(event.options, 1)
        )
        self.chat_view.post_bot(
            f"[bold cyan]❓ Beta-large asks:[/] {escape(event.question)}\n\n{options}\n\n"
            "[dim]Reply with a number, or type your own answer.[/]"
        )
        self.refresh_status()

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

        self.chat_view.post_user(text)

        if self._plan_review.awaiting and self._pipeline is not None:
            self._pipeline.submit_plan_review(text)
            self._plan_review.resolve()
            self.chat_view.post_bot("[yellow]Plan revision submitted.[/]")
            self.refresh_status()
            return

        if self._pipeline is None:
            self.chat_view.post_bot("[red]No pipeline attached.[/]")
            return
        self._pipeline.submit(text)
        self._question_pending = False
        self.refresh_status()

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
            self.chat_view.post_bot(f"📂 Switched to the [b]{cmd}[/] tab.")
        elif cmd == "live":
            self.action_toggle_live()
        elif cmd == "help":
            self.chat_view.post_bot(self._help_text())
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
            self.chat_view.post_bot(
                f"❓ Unknown command: [b]/{cmd}[/]. Try [b]/help[/]."
            )

    def _submit_verdict(self, verdict: str, ack: str) -> None:
        if self._pipeline is not None:
            self._pipeline.submit_plan_review(verdict)
        self._plan_review.resolve()
        self.chat_view.post_bot(ack)
        self.refresh_status()

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
            "[bold red]● LIVE[/]" if self.chat_input.live else "[dim]○ idle[/]"
        )
        audio_src = "mic" if AUDIO_AVAILABLE else "sim"
        workflow_hint = (
            "  │  [cyan]⚙ workflow running[/]"
            if IsWorkflowActive() else ""
        )
        question_hint = (
            "  │  [cyan]❓ beta-large is waiting for your answer[/]"
            if self._question_pending else ""
        )
        plan_hint = (
            "  │  [yellow]📋 awaiting plan review[/]"
            if self._plan_review.awaiting else ""
        )
        return (
            f"  {live}  │  💬 {self.chat_view.message_count} messages  │  "
            f"🎛 audio:{audio_src}{workflow_hint}{question_hint}{plan_hint}  │  "
            f"[dim]Ctrl+L live · Ctrl+K clear · Ctrl+D theme · Ctrl+C quit[/]"
        )

    def refresh_status(self) -> None:
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
            # Return focus so the user can keep typing without an extra click.
            self.chat_input.focus()

    # ── actions ─────────────────────────────────────────────────────────
    def action_toggle_live(self) -> None:
        if self.chat_input.live:
            self.chat_input.exit_live_mode()
            if self._pipeline is not None:
                self._pipeline.set_audio_enabled(False)
            self.chat_view.post_bot("🔇 Live mode off — mic & speakers muted.")
        else:
            self.chat_input.enter_live_mode()
            if self._pipeline is not None:
                self._pipeline.set_audio_enabled(True)
            if AUDIO_AVAILABLE:
                self.chat_view.post_bot(
                    "🎤 Live mode on — mic & speakers active."
                )
            else:
                self.chat_view.post_bot(
                    "🎤 Live mode on (no microphone detected — install "
                    "[b]sounddevice[/] for real input)."
                )
        self.refresh_status()

    def action_clear_chat(self) -> None:
        self.chat_view.clear()
        self.chat_view.post_bot("🧹 Chat cleared.")
        self.refresh_status()

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
        self.chat_view.post_bot("🎨 Theme toggled.")
