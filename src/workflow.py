"""Main orchestrator graph for Beta-1.

Flow:
  START → planning → plan_review → supervisor → format_response → END

Plan review is implemented with LangGraph's native ``interrupt()``: the node
pauses the graph, the caller resumes with ``Command(resume=verdict)``. No
queues, no extra threads.

Invoked via :func:`run_main_graph` — typically from the chat agent's
``delegate_to_planner`` tool when a request needs multi-step work.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.agents.planningagent import planning_node
from src.agents.supervisoragent import supervisor_agent_graph
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.states.main_state import MainState, initial_main_state
from src.utils.errors import NodeFailure, format_app_traceback, node_guard

logger = get_logger("workflow")


# Guarantees one autonomous task executes at a time across all callers.
_WORKFLOW_LOCK = threading.Lock()

_REVIEW_APPROVED = "approved"
_REVIEW_REJECTED = "rejected"
_REJECT_VERDICTS = {"reject", "no", "n", "cancel"}
_APPROVE_VERDICTS = {"", "approve", "yes", "y", "ok"}


# Sync interrupt handler — called when the graph pauses on ``interrupt(...)``.
# Receives the interrupt payload and returns the resume value (verdict /
# revised plan). The workflow-loop blocks here while the user answers.
InterruptHandler = Callable[[dict], str]


@node_guard("workflow", "plan_review")
def plan_review_node(state: MainState) -> dict:
    """Pause for human approval after planning.

    Uses LangGraph's :func:`interrupt`. When the graph resumes, ``response``
    holds whatever the caller passed via ``Command(resume=...)``.

    Verdict semantics:
      - approve / yes / y / ok / "" → continue to supervisor
      - reject / no / n / cancel    → finish without executing
      - anything else               → treat as a revised plan (still approved)
    """
    if not getattr(SETTINGS, "is_planning_review", False):
        return {"next_agent": _REVIEW_APPROVED}

    response = interrupt(
        {
            "implementation_plan": state.get("implementation_plan", ""),
            "action_checklist": state.get("action_checklist", []),
        }
    )
    verdict = (response or "").strip().lower()

    if verdict in _REJECT_VERDICTS:
        logger.info("Plan review: rejected by user")
        return {
            "messages": [AIMessage(content="Plan rejected by user. Halting workflow.")],
            "next_agent": _REVIEW_REJECTED,
        }
    if verdict in _APPROVE_VERDICTS:
        logger.info("Plan review: approved")
        return {"next_agent": _REVIEW_APPROVED}

    logger.info("Plan review: approved with revisions (%d chars)", len(response or ""))
    return {
        "messages": [AIMessage(content="Plan approved with revisions.")],
        "implementation_plan": response,
        "next_agent": _REVIEW_APPROVED,
    }


def route_after_review(state: MainState) -> str:
    return "rejected" if state.get("next_agent") == _REVIEW_REJECTED else "approved"


@node_guard("workflow", "format_response")
def format_response_node(state: MainState) -> dict:
    """Synthesize a final response string from the completed tasks."""
    completed = state.get("completed_tasks", [])
    if not completed:
        summary = "No tasks were completed."
    else:
        lines = [f"Done. Completed {len(completed)} step(s):"]
        for t in completed:
            excerpt_lines = (t.get("result") or "").strip().splitlines()[:1]
            excerpt = excerpt_lines[0] if excerpt_lines else ""
            lines.append(f"- {t['id']}: {excerpt}")
        summary = "\n".join(lines)

    return {
        "final_response": summary,
        "messages": [AIMessage(content=summary)],
    }


def build_main_graph():
    graph = StateGraph(MainState)

    graph.add_node("planning", planning_node)
    graph.add_node("plan_review", plan_review_node)
    graph.add_node("supervisor", supervisor_agent_graph)
    graph.add_node("format_response", format_response_node)

    graph.add_edge(START, "planning")
    graph.add_edge("planning", "plan_review")
    graph.add_conditional_edges(
        "plan_review",
        route_after_review,
        {
            "approved": "supervisor",
            "rejected": "format_response",
        },
    )
    graph.add_edge("supervisor", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile(checkpointer=InMemorySaver())


main_graph = build_main_graph()


def run_main_graph(
    task_summary: str, on_interrupt: Optional[InterruptHandler] = None
) -> str:
    """Run a complex task via the autonomous agent.

    Signature kept for the pipeline's WorkflowLoop. ``on_interrupt`` is unused —
    the autonomous agent has no plan-review interrupt (it self-verifies instead).
    The old planner→supervisor graph below is retained but no longer invoked.
    """
    from src.agents.autonomousagent.autonomous_agent import run_autonomous_agent

    logger.info("Starting workflow for task: %s", task_summary)
    # Serialise: only one autonomous task runs at a time. The single WorkflowLoop
    # already achieves this, but the lock also guards any direct/second caller
    # (e.g. a scheduled task) — the next caller blocks until this one finishes.
    try:
        with _WORKFLOW_LOCK:
            return run_autonomous_agent(task_summary)
    except NodeFailure as nf:
        logger.error("workflow halted: %s", nf.message)
        return nf.message
    except Exception as exc:
        logger.error(
            "workflow crashed — %s\n%s",
            exc,
            format_app_traceback(),
        )
        return f"<workflow:run_main_graph, ERROR: {exc}>"


def _delete_session(thread_id: str) -> None:
    """Drop the InMemorySaver checkpoint for this run."""
    try:
        main_graph.checkpointer.delete_thread(thread_id)
    except Exception:
        logger.debug("session cleanup failed for %s", thread_id, exc_info=True)


def _interrupt_payload(interrupt_obj) -> dict:
    """Best-effort extraction of the interrupt's value across langgraph versions."""
    for attr in ("value", "payload"):
        value = getattr(interrupt_obj, attr, None)
        if value is not None:
            return value if isinstance(value, dict) else {"value": value}
    if isinstance(interrupt_obj, dict):
        return interrupt_obj
    return {"value": interrupt_obj}
