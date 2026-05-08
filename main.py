"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from dotenv import load_dotenv

load_dotenv()

import threading
import asyncio

from src.cli.tui import TUI
from src.pipeline import Pipeline


def main() -> None:
    s = input("Wants GUI? (y/n): ")

    pipeline = Pipeline()
    asyncio.run(pipeline.async_start())
    # pipeline.start()

    if s.lower() == 'y':
        try:
            TUI(pipeline=pipeline).run()
        finally:
            pipeline.stop()
    else:
        threading.Event().wait()

if __name__ == "__main__":
    main()
