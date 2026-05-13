"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

import threading

from dotenv import load_dotenv

load_dotenv()

from src.cli.tui import TUI
from src.pipeline import Pipeline


def main() -> None:
    pipeline = Pipeline()
    pipeline.start()

    if input("Wants GUI? (y/n): ").strip().lower() == "y":
        try:
            TUI(pipeline=pipeline).run()
        finally:
            pipeline.stop()
    else:
        threading.Event().wait()


if __name__ == "__main__":
    main()
