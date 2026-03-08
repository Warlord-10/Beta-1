"""SubAgentState — shared state schema for all sub-agent ReAct loops.

Every sub-agent (file, code, system, search) uses this same state shape
so the supervisor can interact with them uniformly.

Fields:
    messages    – ReAct conversation (system prompt + tool calls + results)
    task        – the TaskItem assigned by the supervisor
    status      – "working" | "done" | "failed"
    result      – final output string from the agent
    iterations  – loop counter (safety cap to prevent infinite loops)
    cwd         – current working directory (used by file & system agents)
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage

from src.states.supervisor_state import TaskItem


class SubAgentState(TypedDict):
    """Shared state for all sub-agent ReAct loops."""
    messages: Annotated[list[AnyMessage], operator.add]
    task: TaskItem
    status: str               # "working" | "done" | "failed"
    result: str
    iterations: int           # safety cap
    cwd: str                  # used by file_agent, system_agent
