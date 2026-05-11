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
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import HarmBlockThreshold, HarmCategory
from langgraph.checkpoint.memory import InMemorySaver

from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.utils.io import IO
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
async def delegate_to_planner(task_summary: str) -> str:
    """Delegate a complex task to the planning workflow.

    Use this when the user's request needs code writing, file modifications,
    multi-step operations, or anything beyond inspection. Returns immediately
    so chat stays responsive; the orchestrator runs in the background and
    the final result is fed back via `dummy_enqueue_result`.
    """
    # Imported lazily to avoid circular imports (workflow → chat agent tools).
    from src.workflow import run_main_graph

    io_unit = IO()

    async def _run() -> None:
        try:
            final = await run_main_graph(task_summary)
        except Exception as exc:
            logger.exception("delegate_to_planner: workflow failed")
            final = f"[delegation failed] {exc}"
        
        io_unit.push_to_llm(final)

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
            thinking_level="minimal"
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

    async def astream(self, user_input: str):
        """Async token stream of assistant content."""

        try:
            stream = self.agent.stream(
                self._turn_input(user_input),
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

                await asyncio.sleep(0)
        except Exception as e:
            print(e)
            yield "Got an error, Try again"
            # else:
            #     print(token.content[0].get("thinking"))
    
    def stream(self, user_input: str):
        """Synchronous one-shot invoke (debug / non-streaming callers)."""

        try:
            stream = self.agent.stream(
                self._turn_input(user_input),
                config=self.config,
                stream_mode="messages",
                version="v2",
            )
            for chunk in stream:
                if chunk.get("type") != "messages":
                    continue
                token, _metadata = chunk.get("data", (None, None))
                if isinstance(token, AIMessageChunk) and isinstance(token.content, str):
                    print(token.content)
                    yield token.content
        except Exception as e:
            print(e)
            yield "Got an error, Try again"