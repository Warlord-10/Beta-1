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
from typing import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
    TodoListMiddleware,
)
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.autonomousagent.permissions import PermissionMiddleware

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

# Asking the user mid-task (pauses the run until they answer).
from src.tools.user_tools import ask_user

logger = get_logger("agents.autonomous")

# ReAct loops need headroom: context → plan → many act/verify steps.
_RECURSION_LIMIT = 100

# Context management. Old tool outputs (file reads, command output) are the
# bulk of a long task's context: past _CLEAR_TOOLS_AT tokens, all but the
# latest _KEEP_TOOL_RESULTS are replaced by a placeholder for the model call
# (state keeps them). Past _SUMMARIZE_AT the older history is summarised.
_CLEAR_TOOLS_AT = 60_000
_KEEP_TOOL_RESULTS = 5
_SUMMARIZE_AT = 150_000
_KEEP_MESSAGES = 20

# Asks the user a question with options and returns their answer.
AskUser = Callable[[str, list[str]], Awaitable[str]]

# Answer given to every question when nobody can respond (sync entry point).
_NO_USER_ANSWER = "The user is not available. Don't do this; continue without it or stop and report."


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
    # User
    ask_user,
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
            timeout=None,   # long steps (e.g. writing a file) can take minutes
        )

        self.summary_llm = llm_factory.create(
            "GEMINI_3_5_FLASH_LITE", temperature=0, max_tokens=4096, timeout=None
        )
        self.agent = self._build_agent(self.llm)

    def _build_agent(self, llm):
        return create_agent(
            model=llm,
            tools=AUTONOMOUS_TOOLS,
            system_prompt=f"{load_prompt('autonomous_agent')}\n\n{environment_context()}",
            checkpointer=self.checkpointer,
            state_schema=ChatState,
            middleware=[
                TodoListMiddleware(),
                PermissionMiddleware(),
                ContextEditingMiddleware(edits=[ClearToolUsesEdit(
                    trigger=_CLEAR_TOOLS_AT,
                    keep=_KEEP_TOOL_RESULTS,
                    exclude_tools=("write_todos", "ask_user"),
                )]),
                SummarizationMiddleware(
                    model=self.summary_llm,
                    trigger=("tokens", _SUMMARIZE_AT),
                    keep=("messages", _KEEP_MESSAGES),
                ),
            ],
        )

    def change_llm(self, new_llm):
        self.agent = self._build_agent(new_llm)

    def format_input(self, user_msg: str) -> dict:
        return {"messages": [HumanMessage(content=user_msg)]}

    def format_task(self, task: str) -> dict:
        # Skills are listed per task — new ones can be created at runtime.
        return self.format_input(f"## Available skills\n{skill_index()}\n\n{task}")

    async def arun(self, task: str, task_id: str, ask: AskUser) -> str:
        """Run one task to completion on its own thread and return the final answer.

        Whenever the run pauses on a question (``ask_user`` or a permission
        check), ``ask`` gets it to the user and the run resumes with the answer.
        """
        config = {
            "configurable": {"thread_id": task_id},
            "recursion_limit": _RECURSION_LIMIT,
        }
        result = await self.agent.ainvoke(self.format_task(task), config=config)
        while interrupts := result.get("__interrupt__"):
            answers = {
                i.id: await ask(i.value["question"], i.value["options"])
                for i in interrupts
            }
            result = await self.agent.ainvoke(Command(resume=answers), config=config)
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
    config = {**agent.config, "recursion_limit": _RECURSION_LIMIT}
    result = agent.agent.invoke(agent.format_task(task), config=config)
    # No user channel on this path: every question gets a "not available".
    while interrupts := result.get("__interrupt__"):
        answers = {i.id: _NO_USER_ANSWER for i in interrupts}
        result = agent.agent.invoke(Command(resume=answers), config=config)
    return result["messages"][-1].text
