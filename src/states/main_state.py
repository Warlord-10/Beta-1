"""MainState — top-level state for the main orchestrator graph.

Fields:
    messages      – conversation history (append-only via operator.add)
    user_query    – raw user input for the current turn
    complexity    – "simple" or "complex" (set by ChatAgent)
    plan          – supervisor's list of task dicts
    results       – collected results from sub-agents
    final_response – formatted response to return to the user
    cwd           – current working directory (persists across turns)
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class MainState(TypedDict):
    """Top-level state shared across the main orchestrator graph."""
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    complexity: str          # "simple" | "complex"
    plan: list[dict]
    results: list[dict]
    final_response: str
    cwd: str
