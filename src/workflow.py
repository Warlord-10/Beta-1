"""Main orchestrator graph for Beta-1.

Flow:
  START → planning → supervisor → format_response → END

Invoked via `run_main_graph(task_summary)` — typically from the chat
agent's `delegate_to_planner` tool when a request needs multi-step work.
"""

from __future__ import annotations

import asyncio
import queue
import uuid

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.planningagent import planning_node
from src.agents.supervisoragent import supervisor_agent_graph
from src.config.events import GlobalQueues
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.states.main_state import MainState, initial_main_state

logger = get_logger("workflow")


_REVIEW_APPROVED = "approved"
_REVIEW_REJECTED = "rejected"


async def plan_review_node(state: MainState) -> dict:
    """Pause for human approval after planning when SETTINGS.is_planning_review is True.

    Posts the implementation plan onto `plan_review_request_queue` for the
    frontend to display, then awaits a response on `plan_review_response_queue`.

    Response semantics:
      - "approve" / "yes" → continue to supervisor.
      - "reject" / "no"   → finish without executing.
      - any other text     → treated as a plan revision and stored back as the
                             new `implementation_plan` (still approved).

    If the setting is off, this node is a no-op pass-through.
    """
    if not getattr(SETTINGS, "is_planning_review", False):
        return {"next_agent": _REVIEW_APPROVED}

    plan_md = state.get("implementation_plan", "")
    checklist = state.get("action_checklist", [])
    GlobalQueues.plan_review_request_queue.put({
        "implementation_plan": plan_md,
        "action_checklist": checklist,
    })

    timeout = float(getattr(SETTINGS, "planning_review_timeout_s", 120))

    def _wait_for_response() -> str:
        try:
            return GlobalQueues.plan_review_response_queue.get(timeout=timeout)
        except queue.Empty:
            return ""

    response = (await asyncio.to_thread(_wait_for_response) or "").strip()
    verdict = response.lower()

    if verdict in {"reject", "no", "n", "cancel"}:
        logger.info("Plan review: rejected by user")
        return {
            "messages": [AIMessage(content="Plan rejected by user. Halting workflow.")],
            "next_agent": _REVIEW_REJECTED,
        }

    if verdict in {"", "approve", "yes", "y", "ok"}:
        logger.info("Plan review: approved")
        return {"next_agent": _REVIEW_APPROVED}

    # Anything else is treated as a revised plan markdown.
    logger.info("Plan review: approved with revisions (%d chars)", len(response))
    return {
        "messages": [AIMessage(content="Plan approved with revisions.")],
        "implementation_plan": response,
        "next_agent": _REVIEW_APPROVED,
    }


def route_after_review(state: MainState) -> str:
    return "rejected" if state.get("next_agent") == _REVIEW_REJECTED else "approved"


def format_response_node(state: MainState) -> dict:
    """Synthesize a final response string from the completed tasks."""
    completed = state.get("completed_tasks", [])
    if not completed:
        summary = "No tasks were completed."
    else:
        lines = [f"Done. Completed {len(completed)} step(s):"]
        for t in completed:
            result_excerpt = (t.get("result") or "").strip().splitlines()[:1]
            excerpt = result_excerpt[0] if result_excerpt else ""
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
    graph.add_conditional_edges("plan_review", route_after_review, {
        "approved": "supervisor",
        "rejected": "format_response",
    })
    graph.add_edge("supervisor", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile(checkpointer=InMemorySaver())


main_graph = build_main_graph()


async def run_main_graph(task_summary: str, cwd: str = "/") -> str:
    """Run the full planning → supervisor → format_response pipeline.

    Returns the synthesized final_response string.
    """
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = await main_graph.ainvoke(initial_main_state(task_summary, cwd=cwd), config=config)
    return result.get("final_response", "")
