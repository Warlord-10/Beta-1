"""Research Agent — self-contained ReAct sub-graph via create_agent.

The supervisor invokes this as a black box via run_research_node(state).
The research agent reads `current_task` from MainState, searches the web,
and returns synthesized findings.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.researchagent.agent_tools import research_agent_tools
from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import MainState
from src.utils.errors import node_guard

logger = get_logger("agents.research_agent")

llm = llm_factory.create("GEMMA_4_31B", temperature=0.3, max_tokens=1024 * 4)
system_prompt = load_prompt("research_agent")

research_agent_graph = create_agent(
    model=llm,
    tools=research_agent_tools,
    system_prompt=system_prompt,
)


@node_guard("research_agent", "run_research_node")
def run_research_node(state: MainState) -> dict:
    """Entry point when invoked by the supervisor.

    Reads the current_task from MainState, runs the research agent,
    and returns the result.
    """
    current_task = state.get("current_task", {})
    task_desc = current_task.get("task_description", "No task provided.")
    input_context = current_task.get("input_context", "")

    task_prompt = f"""
    - Research Task: {task_desc}
    - Additional Context: {input_context}
    """

    result = research_agent_graph.invoke({
        "messages": [HumanMessage(content=task_prompt)],
    })

    final_output = result["messages"][-1].content
    logger.info("Research agent finished: %s", final_output[:200])
    return {
        "messages": [AIMessage(content=f"**Research Agent Complete:**\n{final_output}")],
    }
