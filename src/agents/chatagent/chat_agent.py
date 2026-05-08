"""Chat Agent — primary user-facing tool-calling agent.

Responsibilities:
  1. Answer directly (greetings, general knowledge).
  2. Use read-only tools (file inspection, scheduler, memory, safe shell).
  3. Delegate complex multi-step work to the planning workflow via
     `delegate_to_planner`, which kicks the main orchestrator graph
     and feeds the final result back through `dummy_enqueue_result`.
"""

from __future__ import annotations

import asyncio

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import MainState, initial_main_state

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
# Safe system tools
from src.tools.system_tools.safe_bash import safe_bash

logger = get_logger("agents.chat_agent")


@tool
async def delegate_to_planner(task_summary: str) -> str:
    """Delegate a complex task to the planning workflow.

    Use this when the user's request needs code writing, file modifications,
    multi-step operations, or anything beyond inspection. Returns immediately
    so chat stays responsive; the orchestrator runs in the background and
    the final result is fed back via `dummy_enqueue_result`.
    """
    # Imported lazily to avoid circular imports (workflow → chat agent tools).
    from src.pipeline import dummy_enqueue_result
    from src.workflow import run_main_graph

    async def _run() -> None:
        try:
            final = await run_main_graph(task_summary)
        except Exception as exc:
            logger.exception("delegate_to_planner: workflow failed")
            final = f"[delegation failed] {exc}"
        dummy_enqueue_result(final)

    asyncio.create_task(_run())
    return f"DELEGATED: {task_summary}. I'll follow up when it's done."


CHAT_AGENT_TOOLS = [
    # File inspection
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    safe_bash,

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
    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        self.llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024)
        self.agent = create_agent(
            model=self.llm,
            tools=CHAT_AGENT_TOOLS,
            system_prompt=load_prompt("chat_agent"),
            checkpointer=self.checkpointer,
            state_schema=MainState,
        )

    def chat(self, user_input: str):
        """Synchronous one-shot invoke (debug / non-streaming callers)."""
        return self.agent.invoke(initial_main_state(user_input), config=self.config)

    async def astream(self, user_input: str):
        """Async token stream of assistant content."""
        stream = self.agent.astream(
            initial_main_state(user_input),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        async for chunk in stream:
            if chunk.get("type") != "messages":
                continue
            token, _metadata = chunk.get("data", (None, None))
            if isinstance(token, AIMessageChunk) and isinstance(token.content, str):
                yield token.content
    
    def stream(self, user_input: str):
        """Synchronous one-shot invoke (debug / non-streaming callers)."""
        stream = self.agent.stream(
            initial_main_state(user_input),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        for chunk in stream:
            if chunk.get("type") != "messages":
                continue
            token, _metadata = chunk.get("data", (None, None))
            if isinstance(token, AIMessageChunk) and isinstance(token.content, str):
                yield token.content