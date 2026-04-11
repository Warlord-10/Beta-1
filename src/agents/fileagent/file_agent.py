"""LangGraph graph definition for the File Management Agent.

This agent uses a ReAct loop with access to a current working directory (cwd)
that persists across conversation turns.

Aligned to use SubAgentState for compatibility with the supervisor.
"""

from __future__ import annotations

import operator
from typing import Annotated

from langchain_core.messages import AnyMessage, AIMessage, SystemMessage
from src.llms import llm_factory
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from src.agents.fileagent.agent_tools import file_agent_tools
from src.agents.fileagent.system_prompt import FILE_AGENT_SYSTEM_PROMPT
from src.states.agent_state import SubAgentState
from src.config.logger import get_logger

logger = get_logger("agents.file_agent")

MAX_ITERATIONS = 10


def _get_llm():
    """Lazy LLM initialization via central factory."""
    return llm_factory.create("GEMINI_FLASH", temperature=0).bind_tools(file_agent_tools)


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
                FILE_AGENT_SYSTEM_PROMPT
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


def should_continue(state: SubAgentState) -> str:
    """Decide next step: continue with tools or finish."""
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

def build_file_agent_graph():
    graph = StateGraph(SubAgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(file_agent_tools))
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "finish": "finish",
    })
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)

    return graph.compile()


# Pre-built graph instance for convenience
file_agent_graph = build_file_agent_graph()
