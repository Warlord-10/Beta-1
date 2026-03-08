"""SupervisorState — internal state for the supervisor sub-graph.

The supervisor decomposes the user task into a plan of TaskItems,
processes them one at a time via the router, and validates each result.

Fields:
    messages    – conversation context passed down from MainState
    task        – the overall task description from the user
    plan        – ordered list of TaskItems to execute
    pending     – tasks not yet completed
    completed   – tasks that passed validation
    next_agent  – drives the router node ("file_agent", "code_agent", etc.)
    verdict     – validator output: "approved" | "needs_revision" | "failed"
    iteration   – loop counter for safety cap
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class TaskItem(TypedDict):
    """A single task in the supervisor's plan."""
    id: str
    description: str
    assigned_agent: str       # "file_agent" | "code_agent" | "system_agent" | "search_agent"
    context: dict             # extra context passed to the agent
    status: str               # "pending" | "working" | "done" | "failed"
    result: str               # agent's output for this task


class SupervisorState(TypedDict):
    """State for the supervisor's decompose → route → validate loop."""
    messages: Annotated[list[AnyMessage], operator.add]
    task: str
    plan: list[TaskItem]
    pending: list[TaskItem]
    completed: list[TaskItem]
    next_agent: str           # drives the router
    verdict: str              # "approved" | "needs_revision" | "failed"
    iteration: int
