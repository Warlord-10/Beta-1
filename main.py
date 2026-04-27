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
from src.config.settings import settings
from src.scheduler import scheduler_manager
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
        asr_gen = self._asr.stream()

        for text_chunk in asr_gen:
            if text_chunk is None:
                continue

            full_text += text_chunk
            print(f"{Colors.GREEN}{Colors.BOLD}You ▸{Colors.RESET} {full_text}")

            if not self._is_user_speaking.is_set():
                print("User has stopped speaking")
                full_text = ""
                continue

        print("Run over")


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

        self._llm_chunk_queue: queue.Queue = queue.Queue()
        self._input_queue: queue.Queue = queue.Queue()  # ASR ──► LLM

        thread_id = str(uuid.uuid4())
        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": thread_id}}
        )

        # Build components — inject shared state
        provider_name = settings.TTS_PROVIDER
        provider_config = settings.TTS_CONFIG.get(provider_name, {})

        self._tts = get_tts_engine(provider_name, provider_config)
        self._tts.attach(                        # clean injection
            llm_chunk_queue=self._llm_chunk_queue,
            is_user_speaking=self._is_user_speaking,
        )

        self._asr_service = ASRService(is_user_speaking=self._is_user_speaking)
        self._asr_worker = ASRWorker(self._asr_service, self._input_queue, self._is_user_speaking)

    def _start_threads(self) -> None:
        threading.Thread(
            target=self._asr_worker.run,
            name="asr-worker",
            daemon=True,
        ).start()

        threading.Thread(
            target=self._tts.stream,
            name="tts-worker",
            daemon=True,
        ).start()

    def _stream_to_tts(self, user_message: str) -> None:
        llm_gen = self._chat_agent.stream(user_message)
        for sentence in accumulate_sentences(llm_gen):
            if self._is_user_speaking.is_set():
                logger.debug("Barge-in — aborting LLM stream")
                break
            self._llm_chunk_queue.put(sentence)

    def run(self) -> None:
        print_banner()
        self._start_threads()

        while True:
            user_message = input("User message: ")
            self._llm_chunk_queue.put(user_message)


class Pipeline:
    cwd = settings.DEFAULT_CWD

    def __init__(self):
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        provider_name = settings.TTS_PROVIDER
        provider_config = settings.TTS_CONFIG.get(provider_name, {})
        
        self.asr = ASRService()
        self.tts = get_tts_engine(provider_name, provider_config)
        self.chat_agent = ChatAgent(config=config)

        self.temp_tts = self.tts.stream()
        self.temp_tts.start()

        self.llm_chunk_queue = queue.Queue()

    def process_llm_stream(self, gen):
        for sentence in accumulate_sentences(gen):
            self.llm_chunk_queue.put(sentence)

    def process_tts_stream(self):
        def _print_word(word: str) -> None:
            print(f"{Colors.BLUE}{word}{Colors.RESET}", end=" ", flush=True)

        while True:
            llm_chunk = self.llm_chunk_queue.get()
            if llm_chunk is None:
                break
            self.tts.synthesize(llm_chunk, word_callback=_print_word)
    
    # WIP, not being used currently
    def stream_asr(self):
        final_text = ""
        for chunk in self.asr.stream():
            final_text += chunk

        return final_text + " "

    def run(self):
        tts_thread = threading.Thread(target=self.process_tts_stream, daemon=True)
        tts_thread.start()

        print_banner()
        
        while True:
            prompt = f"{Colors.GRAY}[{self.cwd}]{Colors.RESET} {Colors.GREEN}{Colors.BOLD}You ▸{Colors.RESET} "
            user_input = input(prompt).strip()
            print(f"{Colors.BLUE}{Colors.BOLD}Beta-1 ▸{Colors.RESET}", end="", flush=True)

            if user_input.lower() in ("quit", "exit", "q"):
                print(f"{Colors.YELLOW}👋 Goodbye!{Colors.RESET}")
                break

            if user_input.lower() == "/voice":
                print("Voice mode activated. Say 'quit' to exit voice mode.")
                s = self.stream_asr()
            
            res = self.chat_agent.stream(user_input)
            self.process_llm_stream(res)
            print()

        tts_thread.join()


if __name__ == "__main__":     
    pipeline = PipelineV2()
    pipeline.run()

    # terminal_gui = TUI()
    # terminal_gui.run()
    
    



