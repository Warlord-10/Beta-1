"""SubAgentState — shared state schema for supervisor-managed sub-agents.

Used by agents that the supervisor dispatches to (research, file, etc.).
Provides a common shape so the supervisor wrapper can inject the task and
read back the result without knowing agent internals.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class SubAgentState(TypedDict, total=False):
    """State shared by all supervisor-managed sub-agents."""
    messages: Annotated[list[AnyMessage], operator.add]
    task: dict            # {"description": ..., "id": ..., ...}
    cwd: str              # current working directory
    iterations: int       # loop counter for safety cap
    status: str           # "running" | "done" | "failed"
    result: str           # final output text
