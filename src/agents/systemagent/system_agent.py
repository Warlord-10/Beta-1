"""System Agent — self-contained ReAct sub-graph for shell commands and file operations.

Sub-graph flow:
  START → system_node → route → tools → system_node (loop)
                              → END (no more tool calls)

The supervisor invokes this as a black box via system_agent_graph.invoke(state).
The system agent reads `current_task` from MainState and works on it.

NOTE: This agent is built but NOT yet wired into the supervisor.
      Add it to supervisor routing when ready.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from src.llms import llm_factory
from src.states.main_state import MainState
from src.agents.systemagent.agent_tools import system_agent_tools
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("agents.system_agent")

MAX_SYSTEM_ITERATIONS = 10

# All tools available to the system agent: system tools + file tools
all_system_tools = [*system_agent_tools]

# Also include file tools for file system operations
from src.tools.file_tools import file_tools
all_system_tools.extend(file_tools)


# ── Graph node ───────────────────────────────────────────────────────

def system_node(state: MainState) -> dict:
    """ReAct-style system node — executes commands and file operations."""
    current_task = state.get("current_task", {})
    task_desc = current_task.get("task_description", "No task provided.")
    input_context = current_task.get("input_context", "")
    cwd = state.get("cwd", ".")

    system_prompt = load_prompt("system_agent")

    llm = llm_factory.create("GEMINI_FLASH", temperature=0, max_tokens=1024 * 4)
    llm_with_tools = llm.bind_tools(all_system_tools)

    messages = [
        SystemMessage(content=f"{system_prompt}\n\nCurrent working directory: {cwd}"),
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

    logger.info("System agent response: %s", result.content[:200] if result.content else "[tool calls]")

    return {
        "messages": [result],
    }


# ── Routing ──────────────────────────────────────────────────────────

def should_continue(state: MainState) -> str:
    """Route after system_node: if tool calls pending → tools, else → done."""
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "done"


# ── Build sub-graph ──────────────────────────────────────────────────

def build_system_agent_graph():
    graph = StateGraph(MainState)

    graph.add_node("system_node", system_node)
    graph.add_node("tools", ToolNode(all_system_tools))

    # Entry
    graph.add_edge(START, "system_node")

    # System node → tools (ReAct loop) or END
    graph.add_conditional_edges("system_node", should_continue, {
        "tools": "tools",
        "done": END,
    })

    # Tools → back to system node
    graph.add_edge("tools", "system_node")

    return graph.compile()


system_agent_graph = build_system_agent_graph()
