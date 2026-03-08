"""Main orchestrator graph for Beta-1 personal assistant.

Architecture:
  User → chat_agent (classify)
       → simple:  direct response → END
       → complex: supervisor_subgraph → chat_agent (format) → END

The supervisor subgraph internally runs:
  supervisor → router → {file|code|system|search}_agent → validator → supervisor (loop)
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from src.states.main_state import MainState
from src.agents.chatagent.system_prompt import CHAT_AGENT_SYSTEM_PROMPT
from src.config.settings import DEFAULT_CWD
from src.config.logger import get_logger

logger = get_logger("workflow")


def _get_llm():
    """Lazy LLM initialization."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        max_output_tokens=1024,
    )


# ── Node wrappers ────────────────────────────────────────────────────

def chat_classify_node(state: MainState) -> dict:
    """Run the chat agent's classify step."""
    llm = _get_llm()

    messages = [
        SystemMessage(content=CHAT_AGENT_SYSTEM_PROMPT),
        *state["messages"],
    ]

    result = llm.invoke(messages)
    raw = result.content.strip()

    # Parse JSON
    try:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        parsed = {"complexity": "simple", "response": raw, "task_summary": ""}

    complexity = parsed.get("complexity", "simple")
    response = parsed.get("response", "")
    task_summary = parsed.get("task_summary", "")

    logger.info("Classified as %s", complexity)

    updates = {
        "complexity": complexity,
        "user_query": state["messages"][-1].content if state["messages"] else "",
    }

    if complexity == "simple":
        updates["final_response"] = response
        updates["messages"] = [AIMessage(content=response)]
    else:
        updates["final_response"] = ""
        updates["messages"] = [AIMessage(content=f"[Chat Agent] Task classified as complex: {task_summary}")]

    return updates


def supervisor_node(state: MainState) -> dict:
    """Invoke the supervisor sub-graph for complex tasks."""
    from src.agents.supervisoragent import supervisor_agent_graph

    user_query = state.get("user_query", "")

    # Build supervisor input
    supervisor_input = {
        "messages": [HumanMessage(content=user_query)],
        "task": user_query,
        "plan": [],
        "pending": [],
        "completed": [],
        "next_agent": "",
        "verdict": "",
        "iteration": 0,
    }

    result = supervisor_agent_graph.invoke(supervisor_input)

    # Collect all agent results from the supervisor's messages
    agent_results = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage) and msg.content:
            agent_results.append(msg.content)

    combined = "\n\n".join(agent_results)

    return {
        "messages": [AIMessage(content=combined)],
        "results": result.get("completed", []),
    }


def format_final_response(state: MainState) -> dict:
    """Format the final response after supervisor completes."""
    llm = _get_llm()

    messages = [
        SystemMessage(content=(
            "You are Beta-1. Your team of agents has completed the task. "
            "Below are their results. Provide a clear, well-formatted final response to the user.\n"
            "Be concise but thorough. DO NOT mention internal agent names or technical details about the system."
        )),
        *state["messages"],
    ]

    result = llm.invoke(messages)
    return {
        "final_response": result.content,
        "messages": [result],
    }


def response_node(state: MainState) -> dict:
    """Final node — packages the response."""
    return {"final_response": state.get("final_response", "")}


# ── Routing logic ────────────────────────────────────────────────────

def route_after_classify(state: MainState) -> str:
    """Route based on complexity classification."""
    if state.get("complexity") == "complex":
        return "supervisor"
    return "response"


# ── Build main graph ─────────────────────────────────────────────────

def build_main_graph():
    graph = StateGraph(MainState)

    # Nodes
    graph.add_node("chat_classify", chat_classify_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("format_response", format_final_response)
    graph.add_node("response", response_node)

    # Edges
    graph.add_edge(START, "chat_classify")

    graph.add_conditional_edges("chat_classify", route_after_classify, {
        "supervisor": "supervisor",
        "response": "response",
    })

    graph.add_edge("supervisor", "format_response")
    graph.add_edge("format_response", "response")
    graph.add_edge("response", END)

    return graph.compile()


# Compiled graph — import this from anywhere
main_graph = build_main_graph()
