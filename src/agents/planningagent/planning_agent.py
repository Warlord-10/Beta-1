"""Planning Agent — structured plan generation.

Graph flow:
  START → planning_node → END

Takes the user's task from MainState and produces:
  - implementation_plan (narrative approach)
  - action_checklist (ordered TaskItem list for the supervisor)
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.agents import create_agent
from pydantic import BaseModel, Field

from src.llms import llm_factory
from src.states.main_state import MainState
from src.prompts import load_prompt
from src.config.logger import get_logger
from src.agents.planningagent.agent_tools import read_file, list_directory, search_content, search_files, change_directory


class PlanStep(BaseModel):
    """A single step in the action checklist — agent-agnostic."""
    id: str = Field(description="Unique step id e.g. step_1")
    intent: str = Field(description="WHAT this step accomplishes — not HOW, not WHO")
    task_description: str = Field(description="What needs to be done for this step")
    input_context: str = Field(description="Context needed to execute this step")
    depends_on: list[str] = Field(default_factory=list, description="Step ids that must complete first")
    expected_output: str = Field(description="What the supervisor should receive back")


class PlanOutput(BaseModel):
    """Full output from the planning node."""
    task_summary: str = Field(description="A brief summary of the task")
    implementation_plan: str = Field(
        description=(
            "Markdown artifact: (1) context gathered from the workspace, "
            "(2) files to change or actions to take, "
            "(3) optional prose suggesting which agents fit which steps (advisory only)."
        )
    )
    action_checklist: list[PlanStep] = Field(
        description="Ordered list of agent-agnostic steps — describe WHAT, not WHO or HOW"
    )


logger = get_logger("agents.planning")

all_planning_tools = [read_file, list_directory, search_content, search_files, change_directory]

llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 8)
system_prompt = load_prompt("planning_agent")

planning_agent = create_agent(
    model=llm,
    tools=all_planning_tools,
    system_prompt=system_prompt,
    response_format=PlanOutput
)


def planning_node(state: MainState) -> dict:
    logger.info("Data is in planning node")
    """Analyze task, use tools to research, and produce a structured plan."""

    messages = state.get("messages", []) + [
        HumanMessage(content=f"Task: {state['user_query']}")
    ]
    result = planning_agent.invoke({"messages": messages})
    logger.info("planning result: %s", result)
    plan: PlanOutput = result["structured_response"]
    
    logger.info("Plan generated: %s (%d steps)", plan.task_summary, len(plan.action_checklist))
    action_checklist =[
        {
            "id": step.id,
            "task_description": step.task_description,
            "input_context": step.input_context,
            "depends_on": step.depends_on,
            "status": "pending",
            "result": "",
        }
        for step in plan.action_checklist
    ]

    return {
        "messages": [AIMessage(content=f"[Planning Agent] Plan ready with {len(action_checklist)} steps.")],
        "implementation_plan": plan.implementation_plan,
        "action_checklist": action_checklist,
    }