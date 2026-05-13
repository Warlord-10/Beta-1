"""Headless chat pipeline.

Wraps the chat agent, ASR, TTS, and scheduler behind a small callback API so
any frontend (TUI, CLI, web) can drive it without knowing the internals.

Threading model:
  - main thread:        the frontend (Textual TUI) and its event loop.
  - pipeline-loop:      daemon thread that owns its own asyncio loop and runs
                        the chat agent + workflow asynchronously.
  - asr-worker:         daemon thread, sync (sounddevice input + ASR engine).
  - tts-worker:         daemon thread, sync (sounddevice output + TTS engine).

This isolation keeps the TUI's render loop and PortAudio's callbacks from
contending with the LLM/asyncio work for the GIL.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import uuid
from typing import Callable, Optional

from src.agents.chatagent.chat_agent import ChatAgent
from src.utils.io import IO
from src.asr.asr_service import ASRService
from src.config.events import GlobalEvents, GlobalQueues
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.text_utils import accumulate_sentences_async, clean_text
from src.voice import get_tts_engine

logger = get_logger("pipeline")

OnChunk = Callable[[str], None]
OnThinking = Callable[[str], None]
OnTurnStart = Callable[[], None]
OnTurnEnd = Callable[[], None]
OnUserMessage = Callable[[str], None]
OnPlanReview = Callable[[dict], None]


def dummy_enqueue_result(text: str) -> None:
    print("[DUMMY RESPONSE]", text)


class Pipeline:
    """Headless chat pipeline: queues in, callbacks out."""

    def __init__(self) -> None:
        self.io_unit = IO()

        self._stop_event = threading.Event()

        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": str(uuid.uuid4())}}
        )
        self._tts = get_tts_engine(
            SETTINGS.TTS_PROVIDER,
            SETTINGS.TTS_CONFIG.get(SETTINGS.TTS_PROVIDER, {}),
        )
        self._asr_service = ASRService()

        self.scheduler = SchedulerManager()

        self._on_chunk: Optional[OnChunk] = None
        self._on_thinking: Optional[OnThinking] = None
        self._on_turn_start: Optional[OnTurnStart] = None
        self._on_turn_end: Optional[OnTurnEnd] = None
        self._on_user_msg: Optional[OnUserMessage] = None
        self._on_plan_review: Optional[OnPlanReview] = None

        self._threads: list[threading.Thread] = []

    # ── Public API ───────────────────────────────────────────────────────
    def attach_output(
        self,
        on_chunk: OnChunk,
        on_turn_start: Optional[OnTurnStart] = None,
        on_turn_end: Optional[OnTurnEnd] = None,
        on_thinking: Optional[OnThinking] = None,
    ) -> None:
        self._on_chunk = on_chunk
        self._on_turn_start = on_turn_start
        self._on_turn_end = on_turn_end
        self._on_thinking = on_thinking

    def attach_user_input_listener(self, on_user_msg: OnUserMessage) -> None:
        """Called when a user message originates from outside (e.g. ASR)."""
        self._on_user_msg = on_user_msg

    def attach_plan_review_listener(self, on_plan_review: OnPlanReview) -> None:
        """Called when the workflow asks for human plan approval."""
        self._on_plan_review = on_plan_review

    def submit(self, user_message: str) -> None:
        """Queue a user message for the LLM."""
        if user_message and user_message.strip():
            self.io_unit.push_to_llm(user_message.strip())

    def submit_plan_review(self, response: str) -> None:
        """Push the user's plan review verdict back to the workflow."""
        GlobalQueues.plan_review_response_queue.put(response)

    def start(self) -> None:
        """Spin up ASR, TTS, and the async chat/workflow thread."""
        GlobalEvents.set_asr_enabled(True)
        GlobalEvents.set_tts_enabled(True)

        self._spawn(self._asr_loop, "asr-worker")
        self._spawn(self._tts.stream, "tts-worker")
        self._spawn(self._llm_loop, "pipeline-loop")
        self._spawn(self._plan_review_loop, "plan-review-watcher")

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.scheduler.shutdown()
        except Exception:
            logger.exception("scheduler shutdown failed")

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _llm_loop(self) -> None:
        asyncio.run(self._consumer_loop())

    def _fire(self, cb: Optional[Callable], name: str, *args) -> None:
        if cb is None:
            return
        try:
            cb(*args)
        except Exception:
            logger.exception("%s callback failed", name)

    @staticmethod
    def _drain_llm_queue() -> None:
        while True:
            try:
                GlobalQueues.llm_chunk_queue.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _queue_get(q: queue.Queue, timeout: float):
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    async def _consumer_loop(self) -> None:
        while not self._stop_event.is_set():
            user_message = await asyncio.to_thread(
                self._queue_get, GlobalQueues.input_queue, 0.25
            )
            if user_message is None:
                continue
            await self._handle_turn(user_message)

    async def _handle_turn(self, user_message: str) -> None:
        self._drain_llm_queue()
        self._fire(self._on_turn_start, "on_turn_start")

        token_stream = self._chat_agent.astream(user_message)

        async def _content_only(stream):
            async for kind, text in stream:
                if kind == "thinking":
                    self._fire(self._on_thinking, "on_thinking", text)
                    continue
                yield text

        async for sentence in accumulate_sentences_async(_content_only(token_stream)):
            if GlobalEvents.is_user_speaking():
                logger.debug("Barge-in — aborting LLM stream")
                self._drain_llm_queue()
                return

            if GlobalEvents.is_tts_enabled():
                GlobalQueues.llm_chunk_queue.put(sentence)
            self._fire(self._on_chunk, "on_chunk", sentence)

            await asyncio.sleep(0)

        self._fire(self._on_turn_end, "on_turn_end")

    def _plan_review_loop(self) -> None:
        """Watch for plan-review requests from the workflow and forward them."""
        while not self._stop_event.is_set():
            try:
                plan = GlobalQueues.plan_review_request_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self._fire(self._on_plan_review, "on_plan_review", plan)

    def _asr_loop(self) -> None:
        full_text = ""
        for text_chunk in self._asr_service.stream():
            if text_chunk:
                full_text += f" {text_chunk}"

            if GlobalEvents.is_user_speaking() or not full_text.strip():
                continue

            msg = clean_text(full_text)
            full_text = ""

            self._fire(self._on_user_msg, "on_user_msg", msg)
            self.submit(msg)
