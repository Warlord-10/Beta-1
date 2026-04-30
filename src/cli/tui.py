import asyncio
import random

from textual import on, work
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
    SchedulesPane,
    SessionsPane,
    SettingsPane,
    TasksPane,
)


class TUI(App):
    """A modern Textual chat GUI."""

    TITLE = "Claude Terminal"
    SUB_TITLE = "A modern TUI chat experience"

    TAB_IDS = ("chat", "settings", "schedules", "tasks", "sessions", "contexts")

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
        padding: 1 2;
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
        margin: 1 2;
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

    def __init__(self) -> None:
        super().__init__()
        self._live_active = False
        self._message_count = 0

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
            with TabPane("✅ Tasks", id="tasks"):
                yield TasksPane()
            with TabPane("🗂️ Sessions", id="sessions"):
                yield SessionsPane()
            with TabPane("📚 Contexts", id="contexts"):
                yield ContextsPane()
        with Container(id="bottom-area"):
            yield Static(self._status_text(), id="status-bar", markup=True)
            yield AudioBars(id="audio-bars")
            yield Input(
                placeholder="Type a message or /command (try /help, /tasks, /live)…",
                id="chat-input",
            )

    def on_mount(self) -> None:
        self.query_one("#chat-input", Input).focus()
        self._post_bot(
            """
[CYAN][BOLD]
╔════════════════════════════════════════════════╗
║                                                ║
║   ██████  ███████ ████████  █████     ████     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  █████      ██    ███████  ██  ██     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  ███████    ██    ██   ██    ██████   ║
║                                                ║
╚════════════════════════════════════════════════╝
[DIM] Personal AI Assistant • by Deepanshu Joshi
            """
        )

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
        scroll.scroll_end(animate=True)
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
            self._fake_reply(text)

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
            self._post_bot(self._cost_text())
        else:
            self._post_bot(f"❓ Unknown command: [b]/{cmd}[/]. Try [b]/help[/].")

    def _cost_text(self) -> str:
        from datetime import datetime, timedelta, timezone
        from src.cost.store import cost_store

        now = datetime.now(timezone.utc)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_week = now - timedelta(days=7)

        today = cost_store.total_cost(since=start_today)
        week = cost_store.total_cost(since=start_week)
        all_time = cost_store.total_cost()
        rows = cost_store.summary()

        lines = [
            "💰 [bold]LLM Cost[/]\n",
            f"  Today:     ${today:.4f}",
            f"  Last 7d:   ${week:.4f}",
            f"  All time:  ${all_time:.4f}",
        ]
        if rows:
            lines.append("\n  [b]Per model[/]")
            for r in rows:
                lines.append(
                    f"    {r['registry_key']} ({r['provider']}): "
                    f"${r['estimated_cost']:.4f} — "
                    f"{int(r['input_tokens']):,} in / "
                    f"{int(r['output_tokens']):,} out / "
                    f"{int(r['cached_tokens']):,} cached "
                    f"({int(r['call_count'])} calls)"
                )
        else:
            lines.append("\n  No usage recorded yet.")
        return "\n".join(lines)

    def _help_text(self) -> str:
        return (
            "📖 [bold]Available commands[/]\n\n"
            "  [b]/chat[/]       Open the chat tab\n"
            "  [b]/settings[/]   Open settings\n"
            "  [b]/schedules[/]  Open your schedules\n"
            "  [b]/tasks[/]      Open your tasks\n"
            "  [b]/sessions[/]   Open past sessions\n"
            "  [b]/contexts[/]   Open loaded contexts\n"
            "  [b]/live[/]       Toggle live audio visualizer (Ctrl+L)\n"
            "  [b]/clear[/]      Clear the conversation (Ctrl+K)\n"
            "  [b]/theme[/]      Toggle dark/light theme (Ctrl+D)\n"
            "  [b]/cost[/]       Show LLM cost summary\n"
            "  [b]/help[/]       Show this help\n"
            "  [b]/quit[/]       Exit (Ctrl+C)"
        )

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
        self._refresh_status()
        self._post_bot("🧹 Chat cleared.")

    def action_toggle_dark(self) -> None:
        # Works across recent Textual versions.
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

    # --- fake bot replies -----------------------------------------------------
    @work(exclusive=False)
    async def _fake_reply(self, user_text: str) -> None:
        # Small "typing" delay for realism
        await asyncio.sleep(0.4 + random.random() * 0.6)
        snippets = [
            "Got it! Tell me more.",
            f"Interesting take on \"{user_text[:40]}\" — what led you there?",
            "Mm, I hear you. What's the outcome you're hoping for?",
            "Let's dig in. Which part is most important to you?",
            "✨ Noted. I'll keep that in context for the rest of our chat.",
        ]
        self._post_bot(random.choice(snippets))

    # --- cleanup --------------------------------------------------------------
    async def on_unmount(self) -> None:
        try:
            self.query_one("#audio-bars", AudioBars).stop()
        except Exception:
            pass

