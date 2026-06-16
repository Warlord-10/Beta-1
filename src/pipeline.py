from __future__ import annotations

import queue
import threading
import uuid

from src.agents.chatagent.chat_agent import ChatAgent
from src.asr.asr_service import ASRService
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.io import IO
from src.utils.text_utils import accumulate_sentences, clean_text
from src.voice.tts_service import TTSService
from src.config.global_events import *
from src.config.global_queues import *

logger = get_logger("pipeline")


# Cap for chat input/output logging — long bot replies otherwise drown the log.
_LOG_TRUNCATE = 600


def _summarise(text: str, limit: int = _LOG_TRUNCATE) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


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

        self._tts = TTSService()
        self._asr = ASRService()
        self._scheduler = SchedulerManager()

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
        PlanReviewResponseQueue.put(response)

    def set_audio_enabled(self, enabled: bool) -> None:
        """Gate mic capture and TTS playback together."""
        ToggleASR(enabled)
        ToggleTTS(enabled)

    def start(self) -> None:
        """Spin up ASR, TTS, chat, and workflow threads.

        Audio is OFF by default — the frontend enables it via
        :meth:`set_audio_enabled` (the TUI does this on live mode).
        """
        self.set_audio_enabled(False)
        self._SpawnThread(self._asr_loop, "asr-worker")
        self._SpawnThread(self._tts.stream, "tts-worker")
        self._SpawnThread(self._ChatLoop, "chat-loop")
        self._SpawnThread(self._workflow_loop, "workflow-loop")

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.scheduler.shutdown()
        except Exception:
            logger.exception("scheduler shutdown failed")

    # ── Internals ─────────────────────────────────────────────────────
    def _SpawnThread(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _safe_call(self, fn, *args, name: str) -> None:
        try:
            fn(*args)
        except Exception:
            logger.exception("%s listener callback failed", name)

    def _ChatLoop(self) -> None:
        while not self._stop_event.is_set():
            try:
                user_message = self.io_unit.get_from_llm()
            except queue.Empty:
                continue
            self._HandleTurn(user_message)

    def _HandleTurn(self, user_message: str) -> None:
        DrainLLMQueue()
        logger.info("chat input ← %s", _summarise(user_message))
        self._safe_call(self._listener.on_turn_start, name="on_turn_start")

        thinking_buf: list[str] = []
        content_buf: list[str] = []

        def content_only(stream):
            for kind, text in stream:
                if kind == "thinking":
                    thinking_buf.append(text)
                    self._safe_call(
                        self._listener.on_thinking, text, name="on_thinking"
                    )
                    continue
                content_buf.append(text)
                yield text

        token_stream = self._chat_agent.stream(user_message)
        aborted = False

        self._asr_service.set_vad_threshold(0.9)

        for sentence in accumulate_sentences(content_only(token_stream)):
            if GlobalEvents.CheckUserBargeIn():
                logger.debug("Barge-in — aborting LLM stream")
                DrainLLMQueue()
                aborted = True
                break
            if GlobalEvents.IsTTSEnabled():
                GlobalQueues.llm_chunk_queue.put(sentence)
            self._safe_call(self._listener.on_chunk, sentence, name="on_chunk")

        self._asr_service.reset_vad_threshold()

        if thinking_buf:
            logger.info("chat thinking … %s", _summarise("".join(thinking_buf)))
        suffix = " [aborted by barge-in]" if aborted else ""
        logger.info("chat output → %s%s", _summarise("".join(content_buf)), suffix)

        if not aborted:
            self._safe_call(self._listener.on_turn_end, name="on_turn_end")

    # ── workflow-loop (sync; blocking graph execution) ───────────────
    def _workflow_loop(self) -> None:


        while not self._stop_event.is_set():
            try:
                task_summary = ComplexTaskQueue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                ToggleWorkflow(True)
                final = run_main_graph(task_summary, on_interrupt=self._handle_workflow_interrupt)
            except Exception:
                logger.exception("workflow run failed")
                final = "[workflow failed]"
            finally:
                ToggleWorkflow(False)

            self.io_unit.push_to_llm(final)

    def _handle_workflow_interrupt(self, payload: dict) -> str:
        self._safe_call(
            self._listener.on_plan_review, payload, name="on_plan_review"
        )
        return PlanReviewResponseQueue.get()

    # ── asr-worker ────────────────────────────────────────────────────
    def _asr_loop(self) -> None:
        full_text = ""
        for text_chunk in self._asr_service.stream():
            if text_chunk:
                full_text += f" {text_chunk}"
            if GlobalEvents.CheckUserBargeIn() or not full_text.strip():
                continue
            msg = clean_text(full_text)
            full_text = ""
            self._safe_call(
                self._listener.on_user_message, msg, name="on_user_message"
            )
            self.submit(msg)


class Pipeline_V2:
    def __init__(self) -> None:
        self.io_unit = IO()

        self._stop_event = threading.Event()
        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": str(uuid.uuid4())}}
        )

        self._tts = TTSService(provider="kokoro", config={"voice_name": "af_heart", "speed": 1.3})
        self._asr = ASRService()
        self._scheduler = SchedulerManager()

        self._listener: PipelineListener = PipelineListener()
        self._threads: list[threading.Thread] = []

    def _SpawnThread(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def start(self):
        self._SpawnThread(self.ASRLoop, "asr-worker")
        self._SpawnThread(self._tts.stream, "tts-worker")
        self._SpawnThread(self.ChatLoop, "chat-loop")
        self._SpawnThread(self.WorkflowLoop, "workflow-loop")

        ToggleASR(True)
        ToggleTTS(True)

    def ChatLoop(self):
        while True:
            try:
                user_msg = self.io_unit.get_from_llm()
                self.CallChatAgent(user_msg)
            except queue.Empty:
                continue

    def CallChatAgent(self, user_msg):
        print("Got a new msg: ", user_msg)
        response_stream = self._chat_agent.stream(user_msg)

        self._asr.set_vad_threshold(0.9)
        
        for res_chunk in accumulate_sentences(response_stream):
            print("res_chunk: ", res_chunk)
            LLMChunkQueue.put(clean_text(res_chunk))
        
        self._asr.reset_vad_threshold()

    def ASRLoop(self):
        final_message = ""
        for text_chunk in self._asr.stream():
            if text_chunk: 
                DrainLLMQueue()
                final_message = final_message + text_chunk.strip()

            if not CheckUserBargeIn() and final_message:
                self.io_unit.push_to_llm(final_message)
                final_message = ""

    def WorkflowLoop(self):
        from src.workflow import run_main_graph
        
        while True:
            try:
                task_summary = ComplexTaskQueue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                ToggleWorkflow(True)
                final = run_main_graph(task_summary, on_interrupt=self._handle_workflow_interrupt)
            except Exception:
                logger.exception("workflow run failed")
                final = "[workflow failed]"
            finally:
                ToggleWorkflow(False)

            self.io_unit.push_to_llm(final)
    
    def _handle_workflow_interrupt(self, payload: dict) -> str:
        # self._safe_call(
        #     self._listener.on_plan_review, payload, name="on_plan_review"
        # )
        return PlanReviewResponseQueue.get()
