from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import (
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from .widgets import AudioBars, ChatMessage, AUDIO_AVAILABLE
from .panes import (
    ContextsPane,
    CostsPane,
    SchedulesPane,
    SessionsPane,
    SettingsPane,
    TasksPane,
)

if TYPE_CHECKING:
    from src.pipeline import Pipeline


class TUI(App):
    """Textual chat GUI bound to the chat pipeline."""

    TITLE = "Beta-1"
    SUB_TITLE = "Personal AI Assistant"

    TAB_IDS = ("chat", "settings", "schedules", "tasks", "costs", "sessions", "contexts")

    CSS = """
    Screen {
        background: $surface;
    }

    #main-tabs {
        height: 1fr;
    }

    TabbedContent Tabs {
        background: $panel;
    }

    #chat-scroll {
        padding: 0 1;
        height: 1fr;
        scrollbar-gutter: stable;
    }

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

    #chat-input {
        margin: 0 1;
        border: round $primary;
    }
    #chat-input:focus {
        border: round $accent;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "toggle_live", "Live audio", show=True),
        Binding("ctrl+k", "clear_chat", "Clear", show=True),
        Binding("ctrl+d", "toggle_dark", "Theme", show=True),
    ]

    def __init__(self, pipeline: Optional["Pipeline"] = None) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._live_active = False
        self._message_count = 0
        self._active_bot_msg: Optional[ChatMessage] = None

    # --- layout ---------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="chat", id="main-tabs"):
            with TabPane("💬 Chat", id="chat"):
                yield VerticalScroll(id="chat-scroll")
            with TabPane("⚙️ Settings", id="settings"):
                yield SettingsPane()
            with TabPane("📅 Schedules", id="schedules"):
                yield SchedulesPane()
            # with TabPane("✅ Tasks", id="tasks"):
            #     yield TasksPane()
            with TabPane("💰 Costs", id="costs"):
                yield CostsPane()
            # with TabPane("🗂️ Sessions", id="sessions"):
            #     yield SessionsPane()
            # with TabPane("📚 Contexts", id="contexts"):
            #     yield ContextsPane()
        with Container(id="bottom-area"):
            yield Static(self._status_text(), id="status-bar", markup=True)
            yield AudioBars(id="audio-bars")
            yield Input(
                placeholder="Type a message or /command (try /help, /cost, /schedules)…",
                id="chat-input",
            )

    def on_mount(self) -> None:
        self.query_one("#chat-input", Input).focus()
        self._post_bot(
            "[bold cyan]Beta-1[/] ready. [dim]Personal AI Assistant • by Deepanshu Joshi[/]"
        )
        if self._pipeline is not None:
            self._pipeline.attach_output(
                on_chunk=self._on_pipeline_chunk,
                on_turn_start=self._on_pipeline_turn_start,
                on_turn_end=self._on_pipeline_turn_end,
            )
            self._pipeline.attach_user_input_listener(self._on_pipeline_user_msg)

        # Auto-refresh live tabs every 30s.
        self.set_interval(30.0, self._refresh_live_tabs)

    # --- pipeline callbacks (run on worker threads) ---------------------------
    def _on_pipeline_turn_start(self) -> None:
        self.call_from_thread(self._start_bot_bubble)

    def _on_pipeline_chunk(self, chunk: str) -> None:
        self.call_from_thread(self._append_to_bot_bubble, chunk)

    def _on_pipeline_turn_end(self) -> None:
        self.call_from_thread(self._end_bot_bubble)

    def _on_pipeline_user_msg(self, text: str) -> None:
        self.call_from_thread(self._post_user, text)

    # --- bot streaming bubble -------------------------------------------------
    def _start_bot_bubble(self) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        msg = ChatMessage("", is_user=False)
        scroll.mount(msg)
        scroll.scroll_end(animate=False)
        self._active_bot_msg = msg

    def _append_to_bot_bubble(self, chunk: str) -> None:
        if self._active_bot_msg is None:
            self._start_bot_bubble()
        assert self._active_bot_msg is not None
        self._active_bot_msg.append(chunk)
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def _end_bot_bubble(self) -> None:
        self._active_bot_msg = None
        self._message_count += 1
        self._refresh_status()

    # --- status bar -----------------------------------------------------------
    def _status_text(self) -> str:
        live = "[bold red]● LIVE[/]" if self._live_active else "[dim]○ idle[/]"
        audio_src = "mic" if AUDIO_AVAILABLE else "sim"
        return (
            f"  {live}  │  💬 {self._message_count} messages  │  "
            f"🎛 audio:{audio_src}  │  "
            f"[dim]Ctrl+L live · Ctrl+K clear · Ctrl+D theme · Ctrl+C quit[/]"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:
            pass

    # --- messaging ------------------------------------------------------------
    def _post(self, text: str, is_user: bool) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.mount(ChatMessage(text, is_user=is_user))
        scroll.scroll_end(animate=False)
        self._message_count += 1
        self._refresh_status()

    def _post_user(self, text: str) -> None:
        self._post(text, True)

    def _post_bot(self, text: str) -> None:
        self._post(text, False)

    # --- input handling -------------------------------------------------------
    @on(Input.Submitted, "#chat-input")
    def on_input_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._post_user(text)
            if self._pipeline is not None:
                self._pipeline.submit(text)
            else:
                self._post_bot("[red]No pipeline attached.[/]")

    # --- commands -------------------------------------------------------------
    def _handle_command(self, raw: str) -> None:
        parts = raw[1:].strip().split()
        if not parts:
            return
        cmd, *_args = parts
        cmd = cmd.lower()

        if cmd in self.TAB_IDS:
            self.query_one(TabbedContent).active = cmd
            self._post_bot(f"📂 Switched to the [b]{cmd}[/] tab.")
        elif cmd == "live":
            self.action_toggle_live()
        elif cmd == "help":
            self._post_bot(self._help_text())
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
            self._post_bot(f"❓ Unknown command: [b]/{cmd}[/]. Try [b]/help[/].")

    def _help_text(self) -> str:
        return (
            "📖 [bold]Available commands[/]\n\n"
            "  [b]/chat[/]       Open the chat tab\n"
            "  [b]/settings[/]   Open settings\n"
            "  [b]/schedules[/]  Open your schedules\n"
            "  [b]/tasks[/]      Open your tasks\n"
            "  [b]/costs[/]      Open the cost tab\n"
            "  [b]/sessions[/]   Open past sessions\n"
            "  [b]/contexts[/]   Open loaded contexts\n"
            "  [b]/live[/]       Toggle live audio visualizer (Ctrl+L)\n"
            "  [b]/clear[/]      Clear the conversation (Ctrl+K)\n"
            "  [b]/theme[/]      Toggle dark/light theme (Ctrl+D)\n"
            "  [b]/cost[/]       Switch to Costs tab\n"
            "  [b]/help[/]       Show this help\n"
            "  [b]/quit[/]       Exit (Ctrl+C)"
        )

    # --- tab refresh ----------------------------------------------------------
    def _refresh_live_tabs(self) -> None:
        self._refresh_pane(SchedulesPane)
        self._refresh_pane(CostsPane)

    def _refresh_pane(self, pane_cls) -> None:
        try:
            pane = self.query_one(pane_cls)
            pane.refresh_data()
        except Exception:
            pass

    @on(TabbedContent.TabActivated)
    def _on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        active = event.tab.id or ""
        # Textual gives back tab ids prefixed with "--content-tab-"; check suffix.
        if active.endswith("schedules"):
            self._refresh_pane(SchedulesPane)
        elif active.endswith("costs"):
            self._refresh_pane(CostsPane)

    # --- actions --------------------------------------------------------------
    def action_toggle_live(self) -> None:
        bars = self.query_one("#audio-bars", AudioBars)
        if self._live_active:
            bars.stop()
            self._live_active = False
            self._refresh_status()
            self._post_bot("🔇 Live audio stopped.")
        else:
            self.run_worker(bars.start(), exclusive=True, group="audio")
            self._live_active = True
            self._refresh_status()
            if AUDIO_AVAILABLE:
                self._post_bot(
                    "🎤 Live audio started — speak into your microphone!"
                )
            else:
                self._post_bot(
                    "🎤 Live audio started in [b]simulation[/] mode.\n"
                    "[dim]Install [b]sounddevice[/] and [b]numpy[/] for real microphone input.[/]"
                )

    def action_clear_chat(self) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        for child in list(scroll.children):
            child.remove()
        self._message_count = 0
        self._active_bot_msg = None
        self._refresh_status()
        self._post_bot("🧹 Chat cleared.")

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
        self._post_bot("🎨 Theme toggled.")

    # --- cleanup --------------------------------------------------------------
    async def on_unmount(self) -> None:
        try:
            self.query_one("#audio-bars", AudioBars).stop()
        except Exception:
            pass
