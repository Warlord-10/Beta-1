"""Autonomous Agent — one self-sustaining ReAct worker for complex tasks.

Entry point: ``run_autonomous_agent(task)`` — called from the workflow behind
the chat agent's ``delegate_to_planner``. The agent:

  1. gathers context (reads/greps/lists before deciding anything),
  2. writes a mutable plan via ``update_plan`` and revises it as it learns,
  3. acts with a real terminal (``agent_bash``) plus structured file tools,
  4. verifies each step (runs it, checks the artifact) before moving on.

No supervisor, no cross-agent handoffs — everything lives in one context, so
results never get lost between steps.
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from src.config.context import environment_context
from src.config.logger import get_logger
from src.config.workflow_context import WORKFLOW_CONTEXT, get_workflow_status
from src.llms import llm_factory
from src.prompts import load_prompt
from src.utils.errors import node_guard

# Structured tools (better than bash: predictable, size-capped output).
from src.tools.file_tools import (
    read_file,
    write_file,
    list_directory,
    search_files,
    search_content,
    get_file_info,
)

# One terminal replaces move/copy/delete/mkdir/git/install/process/env wrappers.
from src.tools.system_tools.agent_bash import agent_bash

# Web research.
from src.tools.search_tools import regular_search, advanced_search, extract_text

logger = get_logger("agents.autonomous")


class _WorkflowCancelled(Exception):
    """Raised to abort the ReAct loop when the user cancels."""


class _CancelCallback(BaseCallbackHandler):
    """Aborts the run at the next LLM or tool boundary if cancel was requested."""

    def _check(self) -> None:
        if WORKFLOW_CONTEXT.is_cancelled():
            raise _WorkflowCancelled()

    def on_llm_start(self, *args, **kwargs) -> None:
        self._check()

    def on_tool_start(self, *args, **kwargs) -> None:
        self._check()


@tool
def update_plan(steps: list[str], files_changed: list[str] | None = None) -> str:
    """Record or revise your task plan as a checklist.

    Call this right after gathering context, then again whenever the plan
    changes — mark steps done, add newly-discovered steps, drop dead ones.
    Prefix each step with its status: ``[ ]`` pending, ``[~]`` in progress,
    ``[x]`` done, ``[!]`` failed/blocked.

    Always pass ``files_changed`` with EVERY file you have created or edited so
    far (via agent_bash or write_file). This is how the user and the chat agent
    see what you touched — keep it accurate and cumulative.

    Args:
        steps: The full current checklist, one item per step.
        files_changed: All files created/edited so far (cumulative, relative paths).

    Returns:
        The rendered plan (also logged and shared with the chat agent).
    """
    WORKFLOW_CONTEXT.set_plan(steps)
    if files_changed:
        WORKFLOW_CONTEXT.add_files(files_changed)
    rendered = "\n".join(f"  {s}" for s in steps)
    logger.info("Plan updated (%d steps):\n%s", len(steps), rendered)
    return f"Plan recorded:\n{rendered}"


AUTONOMOUS_TOOLS = [
    # Context gathering (structured)
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    # Acting
    agent_bash,
    write_file,
    # Planning / shared context
    update_plan,
    get_workflow_status,
    # Research
    regular_search,
    advanced_search,
    extract_text,
]

llm = llm_factory.create("ZAI_GLM_4_7", temperature=0.7, max_tokens=1024 * 4)
system_prompt = load_prompt("autonomous_agent")

autonomous_agent = create_agent(
    model=llm,
    tools=AUTONOMOUS_TOOLS,
    system_prompt=system_prompt,
)

# ReAct loops need headroom: context → plan → many act/verify steps.
_RECURSION_LIMIT = 100


@node_guard("autonomous", "run_autonomous_agent")
def run_autonomous_agent(task: str) -> str:
    """Run the autonomous agent to completion and return its final answer."""
    logger.info("autonomous agent start (cwd=%s): %r", os.getcwd(), task)
    WORKFLOW_CONTEXT.start(task)
    opening = (
        f"{environment_context()}\n"
        f"Terminal commands run from the working directory above — use paths relative to it.\n\n"
        f"Task: {task}"
    )
    try:
        result = autonomous_agent.invoke(
            {"messages": [HumanMessage(content=opening)]},
            config={
                "recursion_limit": _RECURSION_LIMIT,
                "callbacks": [_CancelCallback()],
            },
        )
    except _WorkflowCancelled:
        WORKFLOW_CONTEXT.finish("cancelled")
        logger.info("autonomous agent cancelled by user")
        return "Task cancelled by user before completion."
    except Exception:
        WORKFLOW_CONTEXT.finish("failed")
        raise
    final = result["messages"][-1].content
    WORKFLOW_CONTEXT.finish("done")
    logger.info("autonomous agent done (%d chars)", len(final or ""))
    return final
