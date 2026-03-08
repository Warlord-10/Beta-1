"""LangGraph sub-graph for the Search Agent.

Simple ReAct agent — no verify sub-loop (searches are non-destructive).
  LLM → tool calls → LLM → … → final text response
"""

from __future__ import annotations

import operator
from typing import Annotated

from langchain_core.messages import AnyMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from src.agents.searchagent.agent_tools import search_agent_tools
from src.agents.searchagent.system_prompt import SEARCH_AGENT_SYSTEM_PROMPT
from src.states.agent_state import SubAgentState
from src.config.logger import get_logger

logger = get_logger("agents.search_agent")

MAX_ITERATIONS = 10


def _get_llm():
    """Lazy LLM initialization."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
    ).bind_tools(search_agent_tools)


# ── Graph nodes ──────────────────────────────────────────────────────

def agent_node(state: SubAgentState) -> dict:
    """Invoke the LLM with the current message history."""
    llm = _get_llm()
    messages = list(state["messages"])
    if not any(isinstance(m, SystemMessage) for m in messages):
        task_desc = state.get("task", {}).get("description", "")
        sys_msg = SystemMessage(
            content=SEARCH_AGENT_SYSTEM_PROMPT + f"\n\nCurrent task: {task_desc}"
        )
        messages = [sys_msg] + messages

    response = llm.invoke(messages)
    return {
        "messages": [response],
        "iterations": state.get("iterations", 0) + 1,
    }


def should_continue(state: SubAgentState) -> str:
    """Decide: continue with tools or finish."""
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "finish"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "finish"


def finish_node(state: SubAgentState) -> dict:
    """Extract the final result from the last message."""
    last = state["messages"][-1]
    result = last.content if isinstance(last, AIMessage) else str(last)
    return {"status": "done", "result": result}


# ── Build graph ──────────────────────────────────────────────────────

def build_search_agent_graph():
    graph = StateGraph(SubAgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(search_agent_tools))
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "finish": "finish",
    })
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)

    return graph.compile()


search_agent_graph = build_search_agent_graph()
