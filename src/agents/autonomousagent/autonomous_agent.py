"""Autonomous Agent — one self-sustaining ReAct worker for complex tasks.

Entry point: ``run_autonomous_agent(task)`` — called from the workflow behind
the chat agent's ``delegate_to_planner``. The agent:

  1. gathers context (reads/greps/lists before deciding anything),
  2. for multi-step work, keeps a todo list (``write_todos``) and revises it,
  3. acts with a real terminal (``agent_bash``) plus structured file tools,
  4. verifies each step (runs it, checks the artifact) before moving on.

No supervisor, no cross-agent handoffs — everything lives in one context, so
results never get lost between steps.
"""

from __future__ import annotations

import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.config.context import environment_context
from src.config.logger import get_logger
from src.config.workflow_context import get_workflow_status
from src.llms import llm_factory
from src.observability import Metric, Stopwatch, latency_tracker
from src.prompts import load_prompt
from src.skills import skill_index
from src.states.main_state import ChatState

# Structured tools (better than bash: predictable, size-capped output).
from src.tools.file_tools import (
    read_file,
    write_file,
    edit_file,
    list_directory,
    search_files,
    search_content,
    get_file_info,
)

# One terminal replaces move/copy/delete/mkdir/git/install/process/env wrappers.
from src.tools.system_tools.agent_bash import agent_bash

# Skills: list, load, create, update, archive.
from src.tools.skill_tools.skill_tool import SKILL_TOOLS

# Web research.
from src.tools.search_tools import regular_search, advanced_search, extract_text

logger = get_logger("agents.autonomous")

# ReAct loops need headroom: context → plan → many act/verify steps.
_RECURSION_LIMIT = 100


AUTONOMOUS_TOOLS = [
    # Context gathering (structured)
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    # Acting
    agent_bash,
    edit_file,
    write_file,
    # Shared context
    get_workflow_status,
    # Skills
    *SKILL_TOOLS,
    # Research
    regular_search,
    advanced_search,
    extract_text,
]

class AutonomousAgent:
    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        self.llm = llm_factory.create(
            "GEMINI_3_5_FLASH_LITE",
            temperature=1,
            max_tokens=1024 * 16,
            thinking_level="high",
        )

        self.agent = create_agent(
            model=self.llm,
            tools=AUTONOMOUS_TOOLS,
            system_prompt=f"{load_prompt('autonomous_agent')}\n\n{environment_context()}",
            checkpointer=self.checkpointer,
            state_schema=ChatState,
            middleware=[TodoListMiddleware()],
        )

    def change_llm(self, new_llm):
        self.agent = create_agent(
            model=new_llm,
            tools=AUTONOMOUS_TOOLS,
            system_prompt=f"{load_prompt('autonomous_agent')}\n\n{environment_context()}",
            checkpointer=self.checkpointer,
            state_schema=ChatState,
            middleware=[TodoListMiddleware()],
        )

    def format_input(self, user_msg: str) -> dict:
        return {"messages": [HumanMessage(content=user_msg)]}

    def format_task(self, task: str) -> dict:
        # Skills are listed per task — new ones can be created at runtime.
        return self.format_input(f"## Available skills\n{skill_index()}\n\n{task}")

    async def arun(self, task: str, task_id: str) -> str:
        """Run one task to completion on its own thread and return the final answer."""
        result = await self.agent.ainvoke(
            self.format_task(task),
            config={
                "configurable": {"thread_id": task_id},
                "recursion_limit": _RECURSION_LIMIT,
            },
        )
        return result["messages"][-1].text

    async def async_stream(self, user_msg: str):
        result = self.agent.astream(
            input=self.format_input(user_msg),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        stopwatch = Stopwatch()
        first_token_seen = False
        try:
            async for chunk in result:
                if chunk.get("type", None) == "messages":
                    token, metadata = chunk.get("data", None)
                    if isinstance(token, AIMessageChunk) and isinstance(
                        token.content, str
                    ):
                        if not first_token_seen and token.content:
                            first_token_seen = True
                            latency_tracker.record(
                                Metric.LLM_FIRST_TOKEN, stopwatch.elapsed_ms()
                            )
                        yield token.content

        except Exception:
            logger.exception("chat stream failed")
            yield "LLM is facing some issues."
        finally:
            latency_tracker.record(Metric.LLM_STREAM, stopwatch.elapsed_ms())

    def stream(self, user_msg: str):
        result = self.agent.stream(
            input=self.format_input(user_msg),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        stopwatch = Stopwatch()
        first_token_seen = False
        try:
            for chunk in result:
                if chunk.get("type", None) == "messages":
                    token, metadata = chunk.get("data", None)
                    if isinstance(token, AIMessageChunk) and isinstance(
                        token.content, str
                    ):
                        if not first_token_seen and token.content:
                            first_token_seen = True
                            latency_tracker.record(
                                Metric.LLM_FIRST_TOKEN, stopwatch.elapsed_ms()
                            )
                        yield token.content

        except Exception:
            logger.exception("chat stream failed")
            yield "LLM is facing some issues."
        finally:
            latency_tracker.record(Metric.LLM_STREAM, stopwatch.elapsed_ms())


def run_autonomous_agent(task: str) -> str:
    """Sync entry point for Pipeline_V2's workflow (via run_main_graph)."""
    agent = AutonomousAgent(config={"configurable": {"thread_id": str(uuid.uuid4())}})
    result = agent.agent.invoke(
        agent.format_task(task),
        config={**agent.config, "recursion_limit": _RECURSION_LIMIT},
    )
    return result["messages"][-1].text
