"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from dotenv import load_dotenv

load_dotenv()

import asyncio
import queue
import threading
import time
import uuid
from pprint import pprint

from langchain_core.messages import HumanMessage

from src.agents.chatagent.chat_agent import ChatAgent
from src.asr.asr_service import ASRService
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.text_utils import accumulate_sentences
from src.voice import get_tts_engine
from src.workflow import main_graph
from src.cli.tui import TUI

logger = get_logger("cli")

class Colors:
    RESET      = "\033[0m"
    BOLD       = "\033[1m"
    DIM        = "\033[2m"

    GREEN      = "\033[38;5;114m"     # soft green for user
    BLUE       = "\033[38;5;111m"     # soft blue for bot
    CYAN       = "\033[38;5;80m"      # accent color
    GRAY       = "\033[38;5;245m"     # muted gray
    WHITE      = "\033[38;5;255m"     # bright white
    YELLOW     = "\033[38;5;222m"     # warm yellow


def print_banner():
    """Print a styled ASCII art banner on startup."""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔════════════════════════════════════════════════╗
║                                                ║
║   ██████  ███████ ████████  █████     ████     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  █████      ██    ███████  ██  ██     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  ███████    ██    ██   ██    ██████   ║
║                                                ║
╚════════════════════════════════════════════════╝
{Colors.RESET}
{Colors.DIM}Personal AI Assistant • by Deepanshu Joshi{Colors.RESET}
{Colors.GRAY}Type your request below  •  'quit' to exit{Colors.RESET}
"""
    print(banner)


class ASRWorker:
    """Reads from ASRService and pushes completed utterances to input_queue."""

    def __init__(
        self,
        asr: ASRService,
        input_queue: queue.Queue,
        is_user_speaking: threading.Event,
    ) -> None:
        self._asr = asr
        self._input_queue = input_queue
        self._buffer: list[str] = []
        self._is_user_speaking = is_user_speaking

    def run(self) -> None:
        full_text = ""

        for text_chunk in self._asr.stream():
            if text_chunk:
                full_text += text_chunk
                print(
                    f"\r{Colors.GREEN}{Colors.BOLD}You ▸{Colors.RESET} {full_text}",
                    end="",
                    flush=True,
                )

            if not self._is_user_speaking.is_set() and full_text.strip():
                print()
                self._input_queue.put(full_text.strip())
                full_text = ""


class TTSWorker:
    def __init__(
        self,
        tts,
        llm_chunk_queue: queue.Queue,
    ) -> None:
        self._tts = tts
        self._llm_chunk_queue = llm_chunk_queue

    def run(self) -> None:
        self._tts.stream()


class PipelineV2:
    def __init__(self) -> None:
        self._is_user_speaking = threading.Event()

        # Buffer to maintain the llm output.
        # This buffer is fed to the TTS engine for speech synthesis
        self._llm_chunk_queue: queue.Queue = queue.Queue()

        # Buffer to maintain the user input (text/speech).
        # This buffer is sent to the LLM for response
        self._input_queue: queue.Queue = queue.Queue()

        thread_id = str(uuid.uuid4())
        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": thread_id}}
        )

        # Build components — inject shared state
        provider_name = SETTINGS.TTS_PROVIDER
        provider_config = SETTINGS.TTS_CONFIG.get(provider_name, {})

        # TTS Configuration
        self._tts = get_tts_engine(provider_name, provider_config)
        self._tts.attach(
            llm_chunk_queue=self._llm_chunk_queue,
            is_user_speaking=self._is_user_speaking,
        )

        # ASR Configuration
        self._asr_service = ASRService(is_user_speaking=self._is_user_speaking)
        self._asr_worker = ASRWorker(self._asr_service, self._input_queue, self._is_user_speaking)

        # Scheduler Configuration
        self.scheduler = SchedulerManager()
        self.scheduler.attach_callback(self._push_to_llm)

    def _start_threads(self) -> None:
        if SETTINGS.IS_ASR_ENABLED == "true":
            threading.Thread(
                target=self._asr_worker.run,
                name="asr-worker",
                daemon=True,
            ).start()

        if SETTINGS.IS_TTS_ENABLED == "true":
            threading.Thread(
                target=self._tts.stream,
                name="tts-worker",
                daemon=True,
            ).start()

    def _drain_llm_queue(self) -> None:
        while not self._llm_chunk_queue.empty():
            try:
                self._llm_chunk_queue.get_nowait()
            except queue.Empty:
                break

    def _push_to_llm(self, user_message: str) -> None:
        self._drain_llm_queue()

        llm_gen = self._chat_agent.stream(user_message)
        for sentence in accumulate_sentences(llm_gen):
            print("chunk from llm: ", sentence)
            
            if self._is_user_speaking.is_set():
                logger.debug("Barge-in — aborting LLM stream")
                self._drain_llm_queue()
                return

            if SETTINGS.IS_TTS_ENABLED == "true":
                self._llm_chunk_queue.put(sentence)

    def _stdin_reader(self) -> None:
        while True:
            try:
                line = input("Your input: ")
            except EOFError:
                return
            if line.strip():
                self._input_queue.put(line.strip())

    def run(self) -> None:
        print_banner()
        self._start_threads()
        threading.Thread(
            target=self._stdin_reader,
            name="stdin-reader",
            daemon=True,
        ).start()

        while True:
            user_message = self._input_queue.get()
            print(f"{Colors.BLUE}{Colors.BOLD}Beta-1 ▸{Colors.RESET} ", end="", flush=True)
            self._push_to_llm(user_message)
            print()


if __name__ == "__main__":     
    pipeline = PipelineV2()
    pipeline.run()

    # terminal_gui = TUI()
    # terminal_gui.run()
    
    



