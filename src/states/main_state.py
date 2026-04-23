"""MainState — unified state for the entire Beta-1 multi-agent system.

All agents — planner, supervisor, coding, chat — operate on this single
shared state. Each agent reads/writes only the fields it needs.

Fields:
    messages            - conversation history (append-only via operator.add)
    user_query          - raw user input for the current turn
    complexity          - "simple" or "complex" (set by input classifier)
    implementation_plan - detailed narrative plan from the planning agent
    action_checklist    - ordered list of TaskItem dicts from the planner
    current_task        - the task currently being executed (set by supervisor)
    completed_tasks     - tasks that have been completed (append-only)
    final_response      - formatted response to return to the user
    cwd                 - current working directory (persists across turns)
    iteration           - supervisor loop counter (safety cap)
    next_agent          - supervisor routing target
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class TaskItem(TypedDict):
    """A single task in the action checklist."""
    id: str
    task_description: str
    assigned_agent: str       # "coding_agent" (more agents in the future)
    input_context: str        # extra context passed to the agent
    status: str               # "pending" | "working" | "done" | "failed"
    result: str               # agent's output for this task


class CodingState(TypedDict):
    """State for the coding sub-graph."""
    current_task: TaskItem
    messages: Annotated[list[AnyMessage], operator.add]
    completed_tasks: Annotated[list[TaskItem], operator.add]
    cwd: str


class MainState(TypedDict):
    """Unified state shared across all agents and the orchestrator."""
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    complexity: str                              # "simple" | "complex"
    implementation_plan: str                     # planner narrative
    action_checklist: list[TaskItem]             # planner's ordered steps
    current_task: TaskItem                       # supervisor → coding agent
    completed_tasks: Annotated[list[TaskItem], operator.add]
    final_response: str
    cwd: str
    iteration: int                               # supervisor loop counter
    next_agent: str                              # supervisor routing
    extra_context: Annotated[list[dict], operator.add]  # extra context for the agents
