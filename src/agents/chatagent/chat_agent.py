"""Chat Agent — primary user-facing tool-calling agent.

Responsibilities:
  1. Answer directly (greetings, general knowledge).
  2. Use read-only tools (file inspection, scheduler, memory, safe shell).
  3. Delegate complex multi-step work to the planning workflow via
     ``delegate_to_planner``, which enqueues the task for the
     ``workflow-loop`` thread and returns immediately; the workflow's
     final response is fed back to the user through ``IO.push_to_llm``.

Runs inside the pipeline's ``chat-loop`` thread. Everything here — the
agent itself, its tools, the pregel stream — is sync. Async tools are not
supported (langgraph's ``ToolNode`` invokes them on a sync thread pool).
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import HarmBlockThreshold, HarmCategory
from langgraph.checkpoint.memory import InMemorySaver

from src.config.events import GlobalEvents, GlobalQueues
from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import ChatState
# Read-only file tools
from src.tools.file_tools import (get_file_info, list_directory, read_file,
                                  search_content, search_files)
# Memory tools
from src.tools.memory_tools.daily_memory_tools import (add_to_daily_memory,
                                                       read_daily_memory)
# Scheduler tools
from src.tools.scheduler_tools import (create_scheduled_task,
                                       delete_scheduled_task,
                                       list_scheduled_tasks,
                                       modify_scheduled_task,
                                       toggle_scheduled_task)
# Web search (lightweight — deep research goes through delegate_to_planner)
from src.tools.search_tools import regular_search
# Safe system tools
from src.tools.system_tools.safe_bash import safe_bash

logger = get_logger("agents.chat_agent")


@tool
def delegate_to_planner(task_summary: str) -> str:
    """Delegate a complex task to the planning workflow.
        Args: 
            task_summary: Summary of the task to be delegated
        Returns: 
            Confirmation message of the delegated task.
    """

    GlobalQueues.complex_task_queue.put(task_summary)
    GlobalEvents.set_workflow_active(True)
    return f"""The task has been delegated, final update will be provided once it is completed.
    Tell the user that you will update him once this task is completed.
    """


CHAT_AGENT_TOOLS = [
    # File inspection
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    safe_bash,

    # Web search (quick lookups)
    regular_search,

    # Delegation
    delegate_to_planner,

    # Scheduler
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task,

    # Memory
    add_to_daily_memory,
    read_daily_memory,
]


class ChatAgent:
    """Tool-calling chat agent. Streamed synchronously by the chat-loop."""

    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        self.llm = llm_factory.create(
            "GEMMA_4_31B",
            temperature=1,
            max_tokens=512,
            safety_settings={
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            },
            thinking_level="minimal",
        )
        self.agent = create_agent(
            model=self.llm,
            tools=CHAT_AGENT_TOOLS,
            system_prompt=load_prompt("chat_agent"),
            checkpointer=self.checkpointer,
            state_schema=ChatState,
        )

    @staticmethod
    def _turn_input(user_input: str) -> dict:
        """Per-turn input — only a new HumanMessage. Prior chat history is
        preserved by the checkpointer; planner/supervisor state never enters."""
        return {"messages": [HumanMessage(content=user_input)]}

    def chat(self, user_input: str):
        """Synchronous one-shot invoke (debug / non-streaming callers)."""
        return self.agent.invoke(self._turn_input(user_input), config=self.config)

    def stream(self, user_input: str):
        """Sync generator of ``(kind, text)`` tuples.

        ``kind`` is ``"thinking"`` or ``"content"``. Pregel's sync stream is
        used deliberately (the async stream returns 5xx on our backend, and
        the chat-loop thread is dedicated to this work — no need to yield).
        """
        try:
            for chunk in self.agent.stream(
                self._turn_input(user_input),
                config=self.config,
                stream_mode="messages",
                version="v2",
            ):
                token, _metadata = self._unpack_chunk(chunk)
                if isinstance(token, AIMessageChunk):
                    yield from self._split_token(token)
        except Exception as e:
            logger.exception("chat stream failed")
            yield ("content", f"Got an error: {e}")

    # ── pregel chunk plumbing ────────────────────────────────────────
    @staticmethod
    def _unpack_chunk(chunk):
        """Normalise the two shapes pregel returns for stream_mode='messages'.

        Older versions emit ``{"type": "messages", "data": (token, meta)}``;
        newer versions emit the ``(token, meta)`` tuple directly.
        """
        if isinstance(chunk, tuple) and len(chunk) == 2:
            return chunk
        if isinstance(chunk, dict) and chunk.get("type") == "messages":
            return chunk.get("data", (None, None))
        return (None, None)

    @staticmethod
    def _split_token(token: AIMessageChunk):
        """Yield ``(kind, text)`` parts from an ``AIMessageChunk``.

        Handles both the plain-string content and the list-of-parts shape
        used when extended thinking is enabled.
        """
        content = token.content
        if isinstance(content, str):
            if content:
                yield ("content", content)
            return
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("thinking"):
                    yield ("thinking", part["thinking"])
                elif part.get("type") == "text" and part.get("text"):
                    yield ("content", part["text"])
                elif isinstance(part.get("text"), str) and part["text"]:
                    yield ("content", part["text"])
