"""Headless chat pipeline.

Owns the chat agent, the workflow runner, ASR, TTS, and the scheduler behind
a small listener API so any frontend (TUI, CLI, web) can drive it without
knowing the internals.

Threading model — **all sync, no asyncio anywhere**:
  - main thread:    the frontend (Textual TUI).
  - chat-loop:      consumes ``input_queue``; runs the chat agent's sync
                    ``.stream()`` and forwards chunks / thinking to the
                    listener and TTS queue.
  - workflow-loop:  consumes ``complex_task_queue`` (populated by the
                    ``delegate_to_planner`` tool); runs the orchestrator
                    graph one task at a time via the sync
                    ``main_graph.invoke(...)``. All sub-agents
                    (planner, supervisor, code, research, file, system)
                    are sync and call ``llm.invoke`` — async LLM calls
                    were reliably 500ing on our backend.
  - asr-worker:     daemon thread, sync (sounddevice input + ASR engine).
  - tts-worker:     daemon thread, sync (sounddevice output + TTS engine).

Frontend integration:
  Subclass :class:`PipelineListener` (override only what you need) and
  attach it via :meth:`Pipeline.attach_listener`. Callbacks may fire from
  any worker thread — marshal to your UI thread inside the implementation.
"""

from __future__ import annotations

import queue
import threading
import uuid

from src.agents.chatagent.chat_agent import ChatAgent
from src.asr.asr_service import ASRService
from src.config.events import GlobalEvents, GlobalQueues
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.io import IO
from src.utils.text_utils import accumulate_sentences, clean_text
from src.voice import get_tts_engine

logger = get_logger("pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# Listener
# ─────────────────────────────────────────────────────────────────────────────

class PipelineListener:
    """Override the callbacks you care about; defaults are no-ops.

    Every method may fire from a worker thread — UI frontends must marshal
    each call onto their event loop (e.g. ``app.call_from_thread``).
    """

    def on_turn_start(self) -> None: ...
    def on_chunk(self, chunk: str) -> None: ...
    def on_thinking(self, chunk: str) -> None: ...
    def on_turn_end(self) -> None: ...
    def on_user_message(self, text: str) -> None: ...
    def on_plan_review(self, plan: dict) -> None:
        """Workflow paused on an interrupt; display the plan to the user."""


# Module-level instance so tools running deep inside the chat agent's stream
# (e.g. ``delegate_to_planner``) can reach the pipeline without a hard import
# cycle through every layer.
_INSTANCE: "Pipeline | None" = None


def get_pipeline() -> "Pipeline | None":
    return _INSTANCE


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class Pipeline:
    """Headless chat pipeline: queues in, listener callbacks out."""

    _QUEUE_POLL_S = 0.25

    def __init__(self) -> None:
        global _INSTANCE
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

        self._listener: PipelineListener = PipelineListener()
        self._threads: list[threading.Thread] = []

        _INSTANCE = self

    # ── Public API ────────────────────────────────────────────────────
    def attach_listener(self, listener: PipelineListener) -> None:
        self._listener = listener

    def submit(self, user_message: str) -> None:
        """Queue a user message for the chat agent."""
        if user_message and user_message.strip():
            self.io_unit.push_to_llm(user_message.strip())

    def submit_plan_review(self, response: str) -> None:
        """Resolve a pending plan-review interrupt with the user's verdict."""
        GlobalQueues.plan_review_response_queue.put(response)

    def set_audio_enabled(self, enabled: bool) -> None:
        """Gate mic capture and TTS playback together."""
        GlobalEvents.set_asr_enabled(enabled)
        GlobalEvents.set_tts_enabled(enabled)

    def start(self) -> None:
        """Spin up ASR, TTS, chat, and workflow threads.

        Audio is OFF by default — the frontend enables it via
        :meth:`set_audio_enabled` (the TUI does this on live mode).
        """
        self.set_audio_enabled(False)
        self._spawn(self._asr_loop, "asr-worker")
        self._spawn(self._tts.stream, "tts-worker")
        self._spawn(self._chat_loop, "chat-loop")
        self._spawn(self._workflow_loop, "workflow-loop")

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.scheduler.shutdown()
        except Exception:
            logger.exception("scheduler shutdown failed")

    # ── Internals ─────────────────────────────────────────────────────
    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _safe_call(self, fn, *args, name: str) -> None:
        try:
            fn(*args)
        except Exception:
            logger.exception("%s listener callback failed", name)

    @staticmethod
    def _drain_llm_queue() -> None:
        while True:
            try:
                GlobalQueues.llm_chunk_queue.get_nowait()
            except queue.Empty:
                return

    # ── chat-loop (sync) ─────────────────────────────────────────────
    def _chat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                user_message = GlobalQueues.input_queue.get(
                    timeout=self._QUEUE_POLL_S
                )
            except queue.Empty:
                continue
            self._handle_turn(user_message)

    def _handle_turn(self, user_message: str) -> None:
        self._drain_llm_queue()
        self._safe_call(self._listener.on_turn_start, name="on_turn_start")

        def content_only(stream):
            for kind, text in stream:
                if kind == "thinking":
                    self._safe_call(
                        self._listener.on_thinking, text, name="on_thinking"
                    )
                    continue
                yield text

        token_stream = self._chat_agent.stream(user_message)
        for sentence in accumulate_sentences(content_only(token_stream)):
            if GlobalEvents.is_user_speaking():
                logger.debug("Barge-in — aborting LLM stream")
                self._drain_llm_queue()
                return
            if GlobalEvents.is_tts_enabled():
                GlobalQueues.llm_chunk_queue.put(sentence)
            self._safe_call(self._listener.on_chunk, sentence, name="on_chunk")

        self._safe_call(self._listener.on_turn_end, name="on_turn_end")

    # ── workflow-loop (sync; blocking graph execution) ───────────────
    def _workflow_loop(self) -> None:
        # Lazy import — workflow imports from pipeline indirectly through the
        # chat agent's tool layer.
        from src.workflow import run_main_graph

        while not self._stop_event.is_set():
            try:
                task_summary = GlobalQueues.complex_task_queue.get(
                    timeout=self._QUEUE_POLL_S
                )
            except queue.Empty:
                continue

            GlobalEvents.set_workflow_active(True)
            try:
                final = run_main_graph(
                    task_summary,
                    on_interrupt=self._handle_workflow_interrupt,
                )
            except Exception:
                logger.exception("workflow run failed")
                final = "[workflow failed]"
            finally:
                GlobalEvents.set_workflow_active(False)

            # Surface the result as another input turn so the chat agent
            # can phrase it for the user.
            self.io_unit.push_to_llm(final)

    def _handle_workflow_interrupt(self, payload: dict) -> str:
        """Bridge a graph interrupt to the user via the listener + queue.

        Called on the workflow-loop thread; blocks until the TUI calls
        :meth:`submit_plan_review`.
        """
        self._safe_call(
            self._listener.on_plan_review, payload, name="on_plan_review"
        )
        return GlobalQueues.plan_review_response_queue.get()

    # ── asr-worker ────────────────────────────────────────────────────
    def _asr_loop(self) -> None:
        full_text = ""
        for text_chunk in self._asr_service.stream():
            if text_chunk:
                full_text += f" {text_chunk}"
            if GlobalEvents.is_user_speaking() or not full_text.strip():
                continue
            msg = clean_text(full_text)
            full_text = ""
            self._safe_call(
                self._listener.on_user_message, msg, name="on_user_message"
            )
            self.submit(msg)
