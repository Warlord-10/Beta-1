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
from langchain.agents import create_agent
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("agents.code_agent")

all_coding_tools = [*code_tools, *file_tools]

llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 4)
system_prompt = load_prompt("coding_agent")

coding_agent_graph = create_agent(
    model=llm,
    tools=all_coding_tools,
    system_prompt=system_prompt,
)


async def run_coding_node(state: MainState) -> dict:
    current_task = state.get("current_task", {})
    task_desc = current_task.get("task_description", "No task provided.")
    input_context = current_task.get("input_context", "")

    task_prompt = f"""
    - Task: {task_desc}
    - Input context: {input_context}
    - CWD: {current_task.get("cwd", "/")}
    """
    
    local_messages =[HumanMessage(content=task_prompt)]

    result = await coding_agent_graph.ainvoke({
        "messages": local_messages
    })

    final_output = result["messages"][-1].content
    logger.info("Coding agent finished: %s", final_output[:200])
    return {
        "messages": [AIMessage(content=f"**Coding Agent Complete:**\n{final_output}")],
    }
