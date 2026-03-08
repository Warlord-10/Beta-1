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

import operator
from typing import Annotated, TypedDict
from langchain.agents import AgentState

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from src.config.agent_registry import AGENT_REGISTRY
from src.config.settings import DEFAULT_CWD
from src.config.logger import get_logger

logger = get_logger("main")



class MainState(AgentState):
    """Top-level state shared across the orchestrator graph."""
    messages: Annotated[list[AnyMessage], operator.add]
    next_agent: str 
    cwd: str 

def chat_agent_node(state: MainState):
    chat_graph = AGENT_REGISTRY["CHAT_AGENT"]
    result = chat_graph.invoke({
        "messages": state["messages"],
    })
    return {"messages": result["messages"]}

def file_agent_node(state: MainState):
    file_graph = AGENT_REGISTRY["FILE_AGENT"]
    result = file_graph.invoke({
        "messages": state["messages"],
        "cwd": state["cwd"],
    })
    return {"messages": result["messages"]}

def supervisor_agent_node(state: MainState):
    supervisor_graph = AGENT_REGISTRY["SUPERVISOR_AGENT"]
    result = supervisor_graph.invoke({
        "messages": state["messages"],
    })
    return {"messages": result["messages"]}

def build_main_graph(state: MainState):
    graph = StateGraph(MainState)

    # Add nodes
    graph.add_node("chat_agent", chat_agent_node)
    graph.add_node("file_agent", file_agent_node)
    graph.add_node("supervisor_agent", supervisor_agent_node)

    # Edges
    graph.add_edge(START, "chat_agent")

    graph.add_conditional_edges(
        "supervisor_agent",
        lambda state: state["next_agent"],
        {
            "chat_agent": "chat_agent",
            "file_agent": "file_agent",
            "": END
        }
    )

    graph.add_edge("chat_agent", "supervisor_agent")
    graph.add_edge("file_agent", "supervisor_agent")

    graph.add_edge("chat_agent", END)

    return graph.compile(debug=True)


# Compiled graph — import this from anywhere
main_graph = build_main_graph(MainState(messages=[], next_agent="", cwd=DEFAULT_CWD))
