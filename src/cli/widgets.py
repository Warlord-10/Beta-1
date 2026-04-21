from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

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
        height: auto;
        padding: 1;
    }
    ChatMessage.-user > .bubble {
        width: 70%;
        border: round $primary;
        color: green;
    }
    ChatMessage.-bot > .bubble {
        border: round $success;
        color: blue;
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
        yield Static(f"{self._text}", classes="bubble", markup=True)


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
