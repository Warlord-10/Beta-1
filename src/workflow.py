"""Main orchestrator graph for Beta-1 personal assistant.

Architecture:
  User → chat_agent (tool-calling, handles simple + uses tools)
       → [simple/tool-handled] → END
       → [complex] → planning → supervisor → format_response → END

The chat agent is the primary entry point. It handles:
  - Direct answers (greetings, general knowledge)
  - Tool-assisted answers (reading files, listing dirs, git status, etc.)
  - Delegation to the planning agent for complex tasks

Persistence:
  Uses InMemorySaver checkpointer so messages accumulate across turns
  within the same thread (CLI session).
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from src.llms import cost_tracker
from src.states.main_state import MainState
from src.config.logger import get_logger

logger = get_logger("workflow")


# ── Chat agent nodes ────────────────────────────────────────────────

def chat_agent(state: MainState) -> dict:
    """Primary entry — tool-calling chat agent."""
    from src.agents.chatagent import chat_agent_node
    result = chat_agent_node(state)
    logger.info("\n%s", cost_tracker.get_summary())
    return result


# ── Wrapper nodes for sub-graphs ────────────────────────────────────

def planning_node(state: MainState) -> dict:
    """Invoke the planning sub-graph (black box)."""
    from src.agents.planningagent import planning_agent_graph

    result = planning_agent_graph.invoke(state)

    logger.info("Planning complete: %d steps in action checklist",
                len(result.get("action_checklist", [])))

    return {
        "messages": result.get("messages", [])[-1:],  # Keep only the summary message
        "implementation_plan": result.get("implementation_plan", ""),
        "action_checklist": result.get("action_checklist", []),
    }


def supervisor_node(state: MainState) -> dict:
    """Invoke the supervisor sub-graph (black box)."""
    from src.agents.supervisoragent import supervisor_agent_graph

    result = supervisor_agent_graph.invoke(state)

    completed = result.get("completed_tasks", [])
    logger.info("Supervisor complete: %d tasks done", len(completed))

    return {
        "completed_tasks": completed,
        "iteration": result.get("iteration", 0),
    }


def format_response(state: MainState) -> dict:
    """Format complex task results into user-facing response."""
    from src.agents.chatagent import format_response_node
    result = format_response_node(state)
    logger.info("\n%s", cost_tracker.get_summary())
    return result


# ── Routing ──────────────────────────────────────────────────────────

def route_after_chat_agent(state: MainState) -> str:
    """Route based on complexity — set by the chat agent."""
    if state.get("complexity") == "complex":
        return "planning"
    return "__end__"


# ── Build main graph ─────────────────────────────────────────────────

def build_main_graph():
    graph = StateGraph(MainState)

    # Nodes
    graph.add_node("chat_agent", chat_agent)
    graph.add_node("planning", planning_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("format_response", format_response)

    # Edges
    graph.add_edge(START, "chat_agent")

    graph.add_conditional_edges("chat_agent", route_after_chat_agent, {
        "planning": "planning",
        "__end__": END,
    })

    graph.add_edge("planning", "supervisor")
    graph.add_edge("supervisor", "format_response")
    graph.add_edge("format_response", END)

    # Compile with InMemorySaver for conversation persistence
    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)


# Compiled graph — import this from anywhere
main_graph = build_main_graph()
