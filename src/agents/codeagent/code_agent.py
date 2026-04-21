"""Coding Agent — self-contained ReAct sub-graph.

Sub-graph flow:
  START → coding_node → route → tools → coding_node (loop)
                              → END (no more tool calls)

The supervisor invokes this as a black box via coding_agent_graph.invoke(state).
The coding agent reads `current_task` from MainState and works on it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from src.llms import llm_factory
from src.states.main_state import MainState
from src.agents.codeagent.agent_tools import code_tools, file_tools
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("agents.code_agent")

MAX_CODING_ITERATIONS = 10

# Flat list of all tools available to the coding agent
all_coding_tools = [*code_tools, *file_tools]


# ── Graph node ───────────────────────────────────────────────────────

def coding_node(state: MainState) -> dict:
    """ReAct-style coding node — reasons about the task and calls tools."""
    current_task = state.get("current_task", {})
    task_desc = current_task.get("task_description", "No task provided.")
    input_context = current_task.get("input_context", "")

    system_prompt = load_prompt("coding_agent")

    llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 4)
    llm_with_tools = llm.bind_tools(all_coding_tools)

    messages = [
        SystemMessage(content=system_prompt),
        *state.get("messages", []),
    ]

    # On first call for this task, inject the task as a human message
    has_task_msg = any(
        isinstance(m, HumanMessage) and task_desc in m.content
        for m in state.get("messages", [])
    )
    if not has_task_msg:
        task_prompt = f"Task: {task_desc}"
        if input_context:
            task_prompt += f"\n\nContext: {input_context}"
        messages.append(HumanMessage(content=task_prompt))

    result = llm_with_tools.invoke(messages)

    logger.info("Coding agent response: %s", result.content[:200] if result.content else "[tool calls]")

    return {
        "messages": [result],
    }


# ── Routing ──────────────────────────────────────────────────────────

def should_continue(state: MainState) -> str:
    """Route after coding_node: if tool calls pending → tools, else → done."""
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "done"


# ── Build sub-graph ──────────────────────────────────────────────────

def build_coding_agent_graph():
    graph = StateGraph(MainState)

    graph.add_node("coding_node", coding_node)
    graph.add_node("tools", ToolNode(all_coding_tools))

    # Entry
    graph.add_edge(START, "coding_node")

    # Coding node → tools (ReAct loop) or END
    graph.add_conditional_edges("coding_node", should_continue, {
        "tools": "tools",
        "done": END,
    })

    # Tools → back to coding node
    graph.add_edge("tools", "coding_node")

    return graph.compile()


coding_agent_graph = build_coding_agent_graph()
