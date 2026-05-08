"""Main orchestrator graph for Beta-1.

Flow:
  START → planning → supervisor → format_response → END

Invoked via `run_main_graph(task_summary)` — typically from the chat
agent's `delegate_to_planner` tool when a request needs multi-step work.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.planningagent import planning_node
from src.agents.supervisoragent import supervisor_agent_graph
from src.config.logger import get_logger
from src.states.main_state import MainState, initial_main_state

logger = get_logger("workflow")


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
    graph.add_node("supervisor", supervisor_agent_graph)
    graph.add_node("format_response", format_response_node)

    graph.add_edge(START, "planning")
    graph.add_edge("planning", "supervisor")
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
