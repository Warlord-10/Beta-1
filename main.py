"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from dotenv import load_dotenv

load_dotenv()

from src.cli.tui import TUI
from src.pipeline import Pipeline
import torch
import time
import threading
torch.set_num_threads(4)


def main() -> None:
    pipeline = Pipeline()
    pipeline.start()
    # try:
    #     TUI(pipeline=pipeline).run()
    # finally:
    #     pipeline.stop()
    threading.Event().wait()


if __name__ == "__main__":
    main()
