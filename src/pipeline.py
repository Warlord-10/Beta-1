"""Headless chat pipeline.

Wraps the chat agent, ASR, TTS, and scheduler behind a small callback API so
any frontend (TUI, CLI, web) can drive it without knowing the internals.
"""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Callable, Optional

from src.agents.chatagent.chat_agent import ChatAgent
from src.asr.asr_service import ASRService
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.text_utils import accumulate_sentences
from src.voice import get_tts_engine  # noqa: E402

logger = get_logger("pipeline")

OnChunk = Callable[[str], None]
OnTurnStart = Callable[[], None]
OnTurnEnd = Callable[[], None]
OnUserMessage = Callable[[str], None]


class Pipeline:
    """Headless chat pipeline: queues in, callbacks out."""

    def __init__(self) -> None:
        self._is_user_speaking = threading.Event()
        self._llm_chunk_queue: queue.Queue = queue.Queue()
        self._input_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

        thread_id = str(uuid.uuid4())
        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": thread_id}}
        )

        provider_name = SETTINGS.TTS_PROVIDER
        provider_config = SETTINGS.TTS_CONFIG.get(provider_name, {})
        self._tts = get_tts_engine(provider_name, provider_config)
        self._tts.attach(
            llm_chunk_queue=self._llm_chunk_queue,
            is_user_speaking=self._is_user_speaking,
        )

        self._asr_service = ASRService(is_user_speaking=self._is_user_speaking)

        self.scheduler = SchedulerManager()
        self.scheduler.attach_callback(self.submit)

        self._on_chunk: Optional[OnChunk] = None
        self._on_turn_start: Optional[OnTurnStart] = None
        self._on_turn_end: Optional[OnTurnEnd] = None
        self._on_user_msg: Optional[OnUserMessage] = None

        self._threads: list[threading.Thread] = []

    # ── Public API ───────────────────────────────────────────────────────
    def attach_output(
        self,
        on_chunk: OnChunk,
        on_turn_start: Optional[OnTurnStart] = None,
        on_turn_end: Optional[OnTurnEnd] = None,
    ) -> None:
        self._on_chunk = on_chunk
        self._on_turn_start = on_turn_start
        self._on_turn_end = on_turn_end

    def attach_user_input_listener(self, on_user_msg: OnUserMessage) -> None:
        """Called when a user message originates from outside (e.g. ASR)."""
        self._on_user_msg = on_user_msg

    def submit(self, user_message: str) -> None:
        """Queue a user message for the LLM."""
        if user_message and user_message.strip():
            self._input_queue.put(user_message.strip())

    def start(self) -> None:
        self._spawn(self._consumer_loop, "pipeline-consumer")
        if SETTINGS.IS_ASR_ENABLED == "true":
            self._spawn(self._asr_loop, "asr-worker")
        if SETTINGS.IS_TTS_ENABLED == "true":
            self._spawn(self._tts.stream, "tts-worker")

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.scheduler.shutdown()
        except Exception:
            pass

    # ── Internals ────────────────────────────────────────────────────────
    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _drain_llm_queue(self) -> None:
        while not self._llm_chunk_queue.empty():
            try:
                self._llm_chunk_queue.get_nowait()
            except queue.Empty:
                break

    def _consumer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                user_message = self._input_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self._handle_turn(user_message)


    def _handle_turn(self, user_message: str) -> None:
        """The main function responsible for handling the turns and sending response to the LLM."""
        def tee():
            for token in self._chat_agent.stream(user_message):
                if self._is_user_speaking.is_set():
                    logger.debug("Barge-in — aborting LLM stream")
                    self._drain_llm_queue()
                    return
                if self._on_chunk:
                    try:
                        self._on_chunk(token)
                    except Exception:
                        logger.exception("on_chunk callback failed")
                yield token

        # Drain the queue before starting the new turn
        self._drain_llm_queue()

        # Signal the start of a new turn to the TUI
        if self._on_turn_start:
            try:
                self._on_turn_start()
            except Exception:
                logger.exception("on_turn_start callback failed")

        # Main loop for handling the llm output
        llm_chunk_generator = self._chat_agent.stream(user_message)
        for sentence in accumulate_sentences(llm_chunk_generator):
            if self._is_user_speaking.is_set():
                logger.debug("Barge-in — aborting LLM stream")
                self._drain_llm_queue()
                return

            # Pass the token to the LLM chunk queue for TTS processing
            if SETTINGS.IS_TTS_ENABLED:
                self._llm_chunk_queue.put(sentence)

            # Pass the token to the TUI for display
            if self._on_chunk:
                try:
                    self._on_chunk(sentence)
                except Exception:
                    logger.exception("on_chunk callback failed")
        
        # Signal the end of a new turn to the TUI
        if self._on_turn_end:
            try:
                self._on_turn_end()
            except Exception:
                logger.exception("on_turn_end callback failed")


    def _asr_loop(self) -> None:
        """Main function to handle the ASR streaming and processing the user input"""
        full_text = ""
        for text_chunk in self._asr_service.stream():
            if text_chunk:
                full_text += text_chunk

            # Check if the user is speaking and if there is any text to process
            if not self._is_user_speaking.is_set() and full_text.strip():
                msg = full_text.strip()
                full_text = ""

                # Signal the user input to the TUI
                if self._on_user_msg:
                    try:
                        self._on_user_msg(msg)
                    except Exception:
                        logger.exception("on_user_msg callback failed")

                self.submit(msg)
