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
from src.asr.audio_stream import ASRStream
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



class Pipeline:
    cwd = settings.DEFAULT_CWD

    def __init__(self):
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        provider_name = settings.TTS_PROVIDER
        provider_config = settings.TTS_CONFIG.get(provider_name, {})
        
        self.asr = ASRStream()
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
    pipeline = Pipeline()
    pipeline.run()

    # terminal_gui = TUI()
    # terminal_gui.run()
    
    



