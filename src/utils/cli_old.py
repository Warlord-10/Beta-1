"""
A modern Textual-based chat TUI.

Features
--------
* Top tabs: chat, settings, schedules, tasks, sessions, contexts
* Slash commands for every tab (e.g. /chat, /settings) plus /live, /help, /clear,
  /theme, /quit
* Scrollable chat window where user messages align right and the assistant's
  align left, each bubble exactly 50% of the screen width
* Input docked at the bottom; press Enter to send
* `/live` (or Ctrl+L) toggles a real-time audio-level visualizer that renders
  *just above* the input. Uses the microphone via `sounddevice` if available,
  otherwise falls back to a smooth simulated waveform
* Status bar, keyboard shortcuts, themed bubbles, timestamps, message counter,
  sample data in every tab

Install
-------
    pip install textual
    # Optional, for real microphone input in /live mode:
    pip install sounddevice numpy

Run
---
    python chat_gui.py
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

# Try to import audio stack; fall back to a beautiful simulation if unavailable.
try:
    import numpy as np
    import sounddevice as sd

    AUDIO_AVAILABLE = True
except Exception:  # pragma: no cover
    AUDIO_AVAILABLE = False


# =============================================================================
# Chat message bubble
# =============================================================================
class ChatMessage(Horizontal):
    """A single message bubble aligned to the correct side, 50% wide."""

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0;
    }
    ChatMessage.-user {
        align-horizontal: right;
    }
    ChatMessage.-bot {
        align-horizontal: left;
    }
    ChatMessage > .bubble {
        width: 50%;
        height: auto;
        padding: 1 2;
    }
    ChatMessage.-user > .bubble {
        background: $primary 40%;
        border: round $primary;
        color: $text;
    }
    ChatMessage.-bot > .bubble {
        background: $panel;
        border: round $success;
        color: $text;
    }
    """

    def __init__(self, text: str, is_user: bool = False) -> None:
        super().__init__()
        self._text = text
        self._is_user = is_user
        self._ts = datetime.now().strftime("%H:%M")
        self.add_class("-user" if is_user else "-bot")

    def compose(self) -> ComposeResult:
        if self._is_user:
            header = f"[bold]👤 You[/]  [dim]· {self._ts}[/dim]"
        else:
            header = f"[bold]✨ Assistant[/]  [dim]· {self._ts}[/dim]"
        yield Static(f"{header}\n\n{self._text}", classes="bubble", markup=True)


# =============================================================================
# Live audio visualizer
# =============================================================================
class AudioBars(Widget):
    """A reactive audio-level visualizer that sits above the input."""

    DEFAULT_CSS = """
    AudioBars {
        height: 0;
        padding: 0 2;
        background: $panel 0%;
        content-align: center middle;
    }
    AudioBars.-active {
        height: 5;
        background: $panel;
        border-top: tall $accent;
        border-bottom: tall $accent;
    }
    """

    NUM_BARS = 48
    BAR_CHARS = " ▁▂▃▄▅▆▇█"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._levels: list[float] = [0.0] * self.NUM_BARS
        self._stream = None
        self._sim_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def render(self):
        from rich.text import Text

        t = Text()
        label = " 🎤 LIVE " if self.has_class("-active") else ""
        if label:
            t.append(label, style="bold white on red")
            t.append("  ")
        for level in self._levels:
            idx = max(
                0, min(len(self.BAR_CHARS) - 1, int(level * (len(self.BAR_CHARS) - 1)))
            )
            if level < 0.33:
                color = "bright_green"
            elif level < 0.66:
                color = "yellow"
            else:
                color = "bright_red"
            t.append(self.BAR_CHARS[idx], style=color)
        return t

    async def start(self) -> None:
        """Activate the widget and begin producing levels."""
        self.add_class("-active")
        self._loop = asyncio.get_running_loop()
        if AUDIO_AVAILABLE:
            try:
                self._start_stream()
                return
            except Exception:
                pass
        # Fallback: smoothly simulated waveform
        self._sim_task = asyncio.create_task(self._simulate())

    def stop(self) -> None:
        """Deactivate and release any audio resources."""
        self.remove_class("-active")
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None
        self._levels = [0.0] * self.NUM_BARS
        self.refresh()

    # --- real microphone input ------------------------------------------------
    def _start_stream(self) -> None:
        SAMPLE_RATE = 22050
        BLOCK = 1024

        def callback(indata, frames, time_info, status):  # runs on audio thread
            try:
                samples = indata[:, 0]
                windowed = samples * np.hanning(len(samples))
                spectrum = np.abs(np.fft.rfft(windowed))
                bins = np.array_split(spectrum[: len(spectrum) // 2], self.NUM_BARS)
                mags = np.array([float(np.mean(b)) if len(b) else 0.0 for b in bins])
                norm = np.clip(mags / 12.0, 0, 1).tolist()
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._apply_levels, norm)
            except Exception:
                pass

        self._stream = sd.InputStream(
            channels=1,
            samplerate=SAMPLE_RATE,
            callback=callback,
            blocksize=BLOCK,
        )
        self._stream.start()

    def _apply_levels(self, levels: list[float]) -> None:
        # Smooth transitions so bars don't look jittery
        prev = self._levels
        self._levels = [
            max(0.0, min(1.0, prev[i] * 0.55 + levels[i] * 0.45))
            for i in range(len(levels))
        ]
        self.refresh()

    # --- fallback simulation --------------------------------------------------
    async def _simulate(self) -> None:
        t = 0.0
        while True:
            levels = []
            for i in range(self.NUM_BARS):
                v = (
                    0.30 * (math.sin(t * 2.0 + i * 0.30) + 1) / 2
                    + 0.25 * (math.sin(t * 3.7 + i * 0.15) + 1) / 2
                    + random.random() * 0.25
                )
                # Envelope so mid-range bars feel louder, like a real spectrum
                center_weight = 1.0 - abs(
                    (i - self.NUM_BARS / 2) / (self.NUM_BARS / 2)
                ) * 0.5
                levels.append(min(1.0, v * center_weight))
            self._levels = levels
            self.refresh()
            t += 0.15
            await asyncio.sleep(0.06)


# =============================================================================
# Tab panes (sample content to make the app feel alive)
# =============================================================================
class SettingsPane(Container):
    DEFAULT_CSS = """
    SettingsPane { padding: 2 3; }
    SettingsPane .row { height: auto; width: 100%; margin-bottom: 1; }
    SettingsPane Label.label {
        width: 30%;
        content-align: left middle;
        padding: 1 0;
    }
    SettingsPane Input, SettingsPane Switch { width: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("⚙️  [bold]Settings[/]\n\nCustomize your experience.\n", markup=True)
        with Horizontal(classes="row"):
            yield Label("Display name:", classes="label")
            yield Input(value="Claude User", id="setting-name")
        with Horizontal(classes="row"):
            yield Label("Dark mode:", classes="label")
            yield Switch(value=True, id="setting-dark")
        with Horizontal(classes="row"):
            yield Label("Notifications:", classes="label")
            yield Switch(value=True, id="setting-notif")
        with Horizontal(classes="row"):
            yield Label("Model:", classes="label")
            yield Input(value="claude-opus-4.7", id="setting-model")


class SchedulesPane(Container):
    DEFAULT_CSS = """
    SchedulesPane { padding: 2 3; }
    SchedulesPane DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📅  [bold]Schedules[/]\n", markup=True)
        yield DataTable(id="schedules-table", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Time", "Title", "Repeat", "Status")
        rows = [
            ("09:00", "Morning briefing", "Daily", "✅ Active"),
            ("12:30", "Team standup", "Mon–Fri", "✅ Active"),
            ("18:00", "Email summary", "Daily", "⏸️  Paused"),
            ("Sun 20:00", "Weekly review", "Weekly", "✅ Active"),
        ]
        for row in rows:
            t.add_row(*row)


class TasksPane(Container):
    DEFAULT_CSS = """
    TasksPane { padding: 2 3; }
    TasksPane Checkbox { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("✅  [bold]Tasks[/]\n", markup=True)
        yield Checkbox("Finish writing the Textual GUI demo", value=True)
        yield Checkbox("Review pull request #428", value=False)
        yield Checkbox("Call the dentist", value=False)
        yield Checkbox("Prepare slides for Friday's demo", value=False)
        yield Checkbox("Read chapter 4 of 'Designing ML Systems'", value=False)


class SessionsPane(Container):
    DEFAULT_CSS = """
    SessionsPane { padding: 2 3; }
    SessionsPane ListView { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("🗂️  [bold]Sessions[/]\n", markup=True)
        yield ListView(
            ListItem(
                Static("● [b]Planning Q3 roadmap[/]   [dim](2h ago · 42 messages)[/]")
            ),
            ListItem(
                Static(
                    "○ [b]Debug the payment service[/]   [dim](yesterday · 17 messages)[/]"
                )
            ),
            ListItem(
                Static(
                    "○ [b]Weekend trip brainstorm[/]   [dim](3 days ago · 8 messages)[/]"
                )
            ),
            ListItem(
                Static("○ [b]Resume review[/]   [dim](last week · 23 messages)[/]")
            ),
        )


class ContextsPane(Container):
    DEFAULT_CSS = """
    ContextsPane { padding: 2 3; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📚  [bold]Loaded Contexts[/]\n", markup=True)
        yield Static(
            "• [green]●[/] [b]project-spec.md[/]      [dim]1.2k tokens[/]\n"
            "• [green]●[/] [b]api-reference.pdf[/]    [dim]8.4k tokens[/]\n"
            "• [yellow]●[/] [b]meeting-notes.txt[/]   [dim]0.6k tokens[/]\n"
            "• [dim]○[/]  [b]old-design.md[/]          [dim]unloaded[/]\n\n"
            "[dim]Total active context: 10.2k / 200k tokens[/]",
            markup=True,
        )


# =============================================================================
# Main app
# =============================================================================
class ChatApp(App):
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
        # yield Footer()

    def on_mount(self) -> None:
        self.query_one("#chat-input", Input).focus()
        self._post_bot(
            "👋 Welcome! I'm your terminal assistant.\n\n"
            "Try commands like [bold]/help[/], [bold]/tasks[/], [bold]/live[/] — "
            "or just start chatting."
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
        else:
            self._post_bot(f"❓ Unknown command: [b]/{cmd}[/]. Try [b]/help[/].")

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


def main() -> None:
    ChatApp().run()


if __name__ == "__main__":
    main()