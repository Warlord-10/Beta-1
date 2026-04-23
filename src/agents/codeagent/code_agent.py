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
from langgraph.prebuilt import ToolNode, tools_condition

from src.llms import llm_factory
from src.states.main_state import MainState, CodingState
from src.agents.codeagent.agent_tools import code_tools, file_tools
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("agents.code_agent")

MAX_CODING_ITERATIONS = 10

all_coding_tools = [*code_tools, *file_tools]

def coding_node(state: CodingState) -> dict:
    current_task = state.get("current_task", {})
    task_desc = current_task.get("task_description", "No task provided.")
    input_context = current_task.get("input_context", "")

    system_prompt = load_prompt("coding_agent")

    llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 4)
    llm_with_tools = llm.bind_tools(all_coding_tools)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""
        - Task: {task_desc}
        - Input context: {input_context}
        - CWD: {current_task.get("cwd", "/")}
        """),
        state.get("messages", []),
    ]

    result = llm_with_tools.invoke(messages)

    logger.info("Coding agent response: %s", result.content[:200] if result.content else "[tool calls]")

    return {
        "messages": [result],
    }

def build_coding_agent_graph():
    graph = StateGraph(CodingState)

    graph.add_node("coding_node", coding_node)
    graph.add_node("tools", ToolNode(all_coding_tools))

    graph.add_edge(START, "coding_node")
    graph.add_conditional_edges("coding_node", tools_condition)
    graph.add_edge("tools", "coding_node")

    return graph.compile()


coding_agent_graph = build_coding_agent_graph()
