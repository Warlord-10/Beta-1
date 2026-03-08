"""LangGraph sub-graph for the System Agent.

This agent uses a ReAct loop with a safety + verify step:
  LLM → tool calls → safety check → verify → re-try/rollback

It has its own sub-graph so the safety loop is self-contained.
"""

from __future__ import annotations

import operator
from typing import Annotated

from langchain_core.messages import AnyMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from src.agents.systemagent.agent_tools import system_agent_tools
from src.agents.systemagent.system_prompt import SYSTEM_AGENT_SYSTEM_PROMPT
from src.states.agent_state import SubAgentState
from src.config.logger import get_logger

logger = get_logger("agents.system_agent")

MAX_ITERATIONS = 10


def _get_llm():
    """Lazy LLM initialization."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
    ).bind_tools(system_agent_tools)


# ── Graph nodes ──────────────────────────────────────────────────────

def agent_node(state: SubAgentState) -> dict:
    """Invoke the LLM with the current message history."""
    llm = _get_llm()
    messages = list(state["messages"])
    if not any(isinstance(m, SystemMessage) for m in messages):
        task_desc = state.get("task", {}).get("description", "")
        cwd = state.get("cwd", ".")
        sys_msg = SystemMessage(
            content=(
                SYSTEM_AGENT_SYSTEM_PROMPT
                + f"\n\nCurrent task: {task_desc}"
                + f"\nCurrent working directory: {cwd}"
            )
        )
        messages = [sys_msg] + messages

    response = llm.invoke(messages)
    return {
        "messages": [response],
        "iterations": state.get("iterations", 0) + 1,
    }


def safety_verify_node(state: SubAgentState) -> dict:
    """Safety check + verify the agent's last action."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and not last.tool_calls:
        return {"status": "done", "result": last.content}
    return {"status": "working"}


def should_continue(state: SubAgentState) -> str:
    """Decide next step: continue tools, verify, or stop."""
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "finish"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "safety_verify"


def after_safety(state: SubAgentState) -> str:
    """After safety/verify, either finish or loop back."""
    if state.get("status") == "done":
        return "finish"
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "finish"
    return "agent"


# ── Build graph ──────────────────────────────────────────────────────

def build_system_agent_graph():
    graph = StateGraph(SubAgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(system_agent_tools))
    graph.add_node("safety_verify", safety_verify_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "safety_verify": "safety_verify",
        "finish": END,
    })
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("safety_verify", after_safety, {
        "finish": END,
        "agent": "agent",
    })

    return graph.compile()


system_agent_graph = build_system_agent_graph()
