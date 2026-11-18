from __future__ import annotations

import asyncio
import queue
import threading
import uuid

from src.agents.autonomousagent.autonomous_agent import AutonomousAgent
from src.agents.chatagent.chat_agent import ChatAgent
from src.asr.asr_service import ASRService
from src.config.event_bus import (
    EVENT_BUS,
    Chunk,
    PlanReview,
    TurnEnd,
    TurnStart,
    UserMessage,
)
from src.config.logger import get_logger
from src.observability import Metric, latency_tracker
from src.scheduler.scheduler_manager import SchedulerManager
from src.utils.io import IO
from src.utils.text_utils import (
    accumulate_sentences,
    async_accumulate_sentences,
    clean_text,
)
from src.voice.tts_service import TTSService
from src.config.global_events import *
from src.config.global_queues import *

logger = get_logger("pipeline")


class Pipeline_V2:
    def __init__(self) -> None:
        self.io_unit = IO()

        self._stop_event = threading.Event()
        self._chat_agent = ChatAgent(
            config={"configurable": {"thread_id": str(uuid.uuid4())}}
        )

        self._tts = TTSService()
        self._asr = ASRService()
        self._scheduler = SchedulerManager()

        self._threads: list[threading.Thread] = []

    def _SpawnThread(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def start(self, audio_enabled: bool = True) -> None:
        """Spin up worker threads.

        Audio starts ON for headless voice mode; a GUI frontend passes
        ``audio_enabled=False`` and turns it on via live mode.
        """
        self._SpawnThread(self.ASRLoop, "asr-worker")
        self._SpawnThread(self._tts.stream, "tts-worker")
        self._SpawnThread(self.ChatLoop, "chat-loop")
        self._SpawnThread(self.WorkflowLoop, "workflow-loop")
        self.set_audio_enabled(audio_enabled)

    # ── Frontend command API (GUI → pipeline) ─────────────────────────
    def submit(self, text: str) -> None:
        """Queue a typed/spoken user message for the chat agent."""
        if text and text.strip():
            self.io_unit.push_to_llm(text.strip())

    def submit_plan_review(self, response: str) -> None:
        PlanReviewResponseQueue.put(response)

    def set_audio_enabled(self, enabled: bool) -> None:
        ToggleASR(enabled)
        ToggleTTS(enabled)

    def stop(self) -> None:
        # ponytail: the loops are daemon while-True threads — they die on
        # process exit. stop() just cleans the scheduler for the GUI's finally.
        self._stop_event.set()
        try:
            self._scheduler.shutdown()
        except Exception:
            logger.exception("scheduler shutdown failed")

    def ChatLoop(self):
        while True:
            try:
                user_msg = self.io_unit.get_from_llm()
                self.CallChatAgent(user_msg)
            except queue.Empty:
                continue

    def CallChatAgent(self, user_msg):
        EVENT_BUS.publish(TurnStart())
        with latency_tracker.measure(Metric.TURN):
            response_stream = self._chat_agent.stream(user_msg)
            self._asr.set_vad_threshold(0.9)

            for res_chunk in accumulate_sentences(response_stream):
                if IsTTSEnabled():
                    # TTS-only cleanup: clean_text() strips the boundary space,
                    # which the UI needs to keep chunks from running together.
                    LLMChunkQueue.put(clean_text(res_chunk))
                EVENT_BUS.publish(Chunk(res_chunk))

            self._asr.reset_vad_threshold()
        EVENT_BUS.publish(TurnEnd())

    def ASRLoop(self):
        final_message = ""
        for text_chunk in self._asr.stream():
            if text_chunk:
                DrainLLMQueue()
                # Space between partials — ASR yields one phrase per pause, and
                # bare concatenation glued the last word to the next first word.
                final_message = f"{final_message} {text_chunk.strip()}".strip()

            if not CheckUserBargeIn() and final_message:
                EVENT_BUS.publish(UserMessage(final_message))
                self.io_unit.push_to_llm(final_message)
                final_message = ""

    def WorkflowLoop(self):
        from src.workflow import run_main_graph

        while True:
            try:
                task_id, task_summary = ComplexTaskQueue.get(timeout=1)
                logger.info("Workflow loop received task %s", task_id)
            except queue.Empty:
                continue

            try:
                ToggleWorkflow(True)
                final = run_main_graph(
                    task_summary, on_interrupt=self._handle_workflow_interrupt
                )
            except Exception:
                logger.exception("workflow run failed")
                final = "[workflow failed]"
            finally:
                ToggleWorkflow(False)

            # Feed the result back framed as a completed-task notice — not as if
            # the user said it — so the chat agent announces the outcome instead
            # of "replying" to its own workflow output.
            notice = (
                f"[SYSTEM NOTICE] Delegated background task {task_id} has finished. "
                "Announce the outcome to the user in first person, concisely.\n\n"
                f"Result:\n{final}"
            )
            self.io_unit.push_to_llm(notice)

    def _handle_workflow_interrupt(self, payload: dict) -> str:
        EVENT_BUS.publish(PlanReview(payload))
        return PlanReviewResponseQueue.get()


class AsyncPipeline(Pipeline_V2):
    def __init__(self) -> None:
        super().__init__()
        self._autonomous_agent = AutonomousAgent(
            config={"configurable": {"thread_id": str(uuid.uuid4())}}
        )

    def start(self, audio_enabled: bool = True) -> None:
        self._SpawnThread(self.ASRLoop, "asr-worker")
        self._SpawnThread(self._tts.stream, "tts-worker")
        self.set_audio_enabled(audio_enabled)

    async def run(self, audio_enabled: bool = True) -> None:
        self.start(audio_enabled)
        await asyncio.gather(self.AsyncChatLoop(), self.AsyncWorkflowLoop())

    async def AsyncChatLoop(self):
        while True:
            user_msg = await self.io_unit.async_get_from_llm()
            try:
                await self.CallAsyncChatAgent(user_msg)
            except Exception:
                logger.exception("chat turn failed")

    async def CallAsyncChatAgent(self, user_msg: str):
        EVENT_BUS.publish(TurnStart())
        with latency_tracker.measure(Metric.TURN):
            self._asr.set_vad_threshold(0.9)
            response_stream = self._chat_agent.async_stream(user_msg)

            async for res_chunk in async_accumulate_sentences(response_stream):
                if IsTTSEnabled():
                    LLMChunkQueue.put_nowait(clean_text(res_chunk))
                EVENT_BUS.publish(Chunk(res_chunk))

            self._asr.reset_vad_threshold()
        EVENT_BUS.publish(TurnEnd())
        await self._chat_agent.end_turn()

    async def AsyncWorkflowLoop(self):
        while True:
            try:
                task_id, current_task = await asyncio.to_thread(
                    ComplexTaskQueue.get, timeout=1
                )
            except queue.Empty:
                continue

            try:
                ToggleWorkflow(True)
                final = await self._autonomous_agent.arun(current_task, task_id)
            except Exception:
                logger.exception("workflow run failed")
                final = "[workflow failed]"
            finally:
                ToggleWorkflow(False)

            notice = (
                f"[SYSTEM NOTICE] Delegated background task {task_id} has finished. "
                "Announce the outcome to the user in first person, concisely.\n\n"
                f"Result:\n{final}"
            )
            self.io_unit.push_to_llm(notice)
