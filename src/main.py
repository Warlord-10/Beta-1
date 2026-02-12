"""Main orchestrator graph for Beta-1 personal assistant.

This is the entry-point graph that:
  1. Receives user input.
  2. Routes to the appropriate sub-agent (e.g. file agent).
  3. Returns the final response.

Designed to scale — adding a new agent only requires:
  - importing its sub-graph
  - adding a routing branch
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from src.config.agent_registry import AGENT_REGISTRY



# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class MainState(TypedDict):
    """Top-level state shared across the orchestrator graph."""
    messages: Annotated[list[AnyMessage], operator.add]
    next_agent: str  # which sub-agent to route to ("file_agent", or future agents)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

# Router LLM — lightweight model that only classifies intent
_router_llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0,
)

ROUTER_SYSTEM_PROMPT = """\
You are an intent router for a personal assistant called Beta-1.
Given the user's message, decide which specialised agent should handle it.

Available agents:
  • file_agent — handles ANY file system operation (read, write, list, create, \
move, copy, delete files/directories, get file info).

Rules:
  1. Respond with ONLY the agent name, nothing else.
  2. If no agent fits, respond with "file_agent" as the default for now.

Examples:
  User: "Show me what's in the /tmp folder"  →  file_agent
  User: "Create a new file called notes.txt" →  file_agent
"""


def router_node(state: MainState) -> dict:
    """Classify the user's intent and pick the right sub-agent."""
    response = _router_llm.invoke(
        [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": state["messages"][-1].content},
        ]
    )
    next_agent = response.content.strip().lower()

    # Normalise — map to a known agent, fallback to file_agent
    known_agents = {"file_agent"}
    if next_agent not in known_agents:
        next_agent = "file_agent"

    return {"next_agent": next_agent}


def file_agent_node(state: MainState) -> dict:
    """Invoke the file agent sub-graph and surface its response."""
    file_graph = AGENT_REGISTRY["FILE_AGENT"]
    result = file_graph.invoke({"messages": state["messages"]})
    return {"messages": result["messages"][len(state["messages"]):]}


def route_to_agent(state: MainState) -> str:
    """Conditional edge: route to the chosen agent node."""
    return state["next_agent"]


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_main_graph():
    """Build and compile the main orchestrator graph.

    Flow:
        START → router → (conditional) → file_agent → END
                                       → ... (future agents)
    """
    graph = StateGraph(MainState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("file_agent", file_agent_node)

    # Edges
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        route_to_agent,
        {
            "file_agent": "file_agent",
            # Add future agents here:
            # "web_agent": "web_agent",
        },
    )
    graph.add_edge("file_agent", END)

    return graph.compile()


# Compiled graph — import this from anywhere
main_graph = build_main_graph()
