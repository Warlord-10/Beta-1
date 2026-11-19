"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from src.config.settings import SETTINGS
from src.cli.tui import TUI
from src.pipeline import AsyncPipeline


async def run_gui() -> None:
    # TUI and the pipeline's async loops share one event loop on the main thread.
    pipeline = AsyncPipeline()
    pipeline_task = asyncio.create_task(pipeline.run(audio_enabled=True))
    try:
        await TUI(pipeline=pipeline).run_async()
    finally:
        pipeline_task.cancel()
        pipeline.stop()


def main() -> None:
    gui = SETTINGS.IS_GUI_ENABLED

    # GUI: start muted — the user turns audio on via live mode (Ctrl+L).
    # Headless: audio on so the voice assistant can hear immediately.
    if gui:
        asyncio.run(run_gui())
    else:
        asyncio.run(AsyncPipeline().run(audio_enabled=True))


if __name__ == "__main__":
    main()
