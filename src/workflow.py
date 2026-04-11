"""Main orchestrator graph for Beta-1 personal assistant.

Architecture:
  User → input_node (classify)
       → simple:  chat_response → END
       → complex: planning_graph → supervisor_graph → chat_response → END

The planning and supervisor are self-contained sub-graphs invoked as
black boxes. Changing their internal flow doesn't affect this workflow.
"""

from __future__ import annotations

from typing import Optional, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from src.llms import llm_factory, cost_tracker
from src.states.main_state import MainState
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("workflow")


# ── Input classifier ────────────────────────────────────────────────

class InputClassification(BaseModel):
    """LLM output schema for query classification."""
    complexity: Literal["simple", "complex"] = Field(
        description="Whether the query is 'simple' (direct answer) or 'complex' (needs agents)."
    )
    response: Optional[str] = Field(
        default=None,
        description="Direct response for simple queries. None for complex."
    )


def input_node(state: MainState) -> dict:
    """Classify the user query as simple or complex."""
    llm = llm_factory.create("GEMINI_FLASH", temperature=0.7, max_output_tokens=1024)
    structured_llm = llm.with_structured_output(InputClassification)

    system_prompt = load_prompt("input_classifier")

    messages = [
        SystemMessage(content=system_prompt),
        *state["messages"],
    ]

    result: InputClassification = structured_llm.invoke(messages)

    complexity = result.complexity
    response = result.response or ""

    logger.info("Classified as %s", complexity)

    return {
        "complexity": complexity,
        "final_response": response,
        "user_query": state["messages"][-1].content if state["messages"] else "",
    }


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


# ── Chat response nodes ─────────────────────────────────────────────

def simple_response_node(state: MainState) -> dict:
    """Simple query — response already in state from input_node."""
    from src.agents.chatagent import simple_response_node as _simple
    result = _simple(state)
    logger.info("\n%s", cost_tracker.get_summary())
    return result


def complex_response_node(state: MainState) -> dict:
    """Complex query — chat agent formats the final response."""
    from src.agents.chatagent import complex_response_node as _complex
    result = _complex(state)
    logger.info("\n%s", cost_tracker.get_summary())
    return result


# ── Routing ──────────────────────────────────────────────────────────

def route_after_classify(state: MainState) -> str:
    """Route based on complexity classification."""
    if state.get("complexity") == "complex":
        return "planning"
    return "simple_response"


# ── Build main graph ─────────────────────────────────────────────────

def build_main_graph():
    graph = StateGraph(MainState)

    # Nodes
    graph.add_node("input_node", input_node)
    graph.add_node("planning", planning_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("simple_response", simple_response_node)
    graph.add_node("complex_response", complex_response_node)

    # Edges
    graph.add_edge(START, "input_node")

    graph.add_conditional_edges("input_node", route_after_classify, {
        "planning": "planning",
        "simple_response": "simple_response",
    })

    graph.add_edge("planning", "supervisor")
    graph.add_edge("supervisor", "complex_response")
    graph.add_edge("simple_response", END)
    graph.add_edge("complex_response", END)

    return graph.compile()


# Compiled graph — import this from anywhere
main_graph = build_main_graph()
