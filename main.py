"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

import threading

from dotenv import load_dotenv

load_dotenv()

from src.config.settings import SETTINGS
from src.cli.tui import TUI
from src.pipeline import Pipeline, Pipeline_V2


def main() -> None:
    gui = SETTINGS.IS_GUI_ENABLED

    pipeline = Pipeline_V2()
    # GUI: start muted — the user turns audio on via live mode (Ctrl+L).
    # Headless: audio on so the voice assistant can hear immediately.
    pipeline.start(audio_enabled=not gui)

    if gui:
        try:
            TUI(pipeline=pipeline).run()
        finally:
            pipeline.stop()
    else:
        threading.Event().wait()


if __name__ == "__main__":
    main()
