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
from pydantic import BaseModel, Field

from src.llms import llm_factory
from src.states.main_state import MainState
from src.prompts import load_prompt
from src.config.logger import get_logger
from src.agents.planningagent.agent_tools import read_file, list_directory, search_content, search_files, change_directory

all_planning_tools = [read_file, list_directory, search_content, search_files, change_directory]

logger = get_logger("agents.planning")


# ── Structured output schemas ────────────────────────────────────────

class PlanStep(BaseModel):
    """A single step in the action checklist."""
    id: str = Field(description="Unique step id e.g. step_1")
    intent: str = Field(description="WHAT this step accomplishes — not HOW")
    assigned_agent: str = Field(description="Which agent handles this step")
    task_description: str = Field(description="What the agent needs to do")
    input_context: str = Field(description="What context this agent needs to do its job")
    depends_on: list[str] = Field(default_factory=list, description="Step ids that must complete first")
    expected_output: str = Field(description="What the supervisor should receive back from this agent")


class PlanOutput(BaseModel):
    """Full output from the planning node."""
    task_summary: str = Field(description="A brief summary of the task")
    implementation_plan: str = Field(
        description="Detailed narrative plan: approach, reasoning, architecture decisions, dependencies"
    )
    action_checklist: list[PlanStep] = Field(
        description="Ordered list of steps — intent + agent assignment only, never tool-level instructions"
    )


# ── Graph node ───────────────────────────────────────────────────────

def planning_node(state: MainState) -> dict:
    """Analyze task and produce a structured plan with action checklist."""
    llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 8)
    llm_with_tools = llm.bind_tools(all_planning_tools)
    structured_llm = llm_with_tools.with_structured_output(PlanOutput)

    system_prompt = load_prompt("planning_agent")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Task: {state['user_query']}"),
    ]

    result: PlanOutput = structured_llm.invoke(messages)
    logger.info("Plan generated: %s (%d steps)", result.task_summary, len(result.action_checklist))

    # Convert PlanSteps to TaskItem-compatible dicts
    action_checklist = []
    for step in result.action_checklist:
        action_checklist.append({
            "id": step.id,
            "task_description": step.task_description,
            "assigned_agent": step.assigned_agent,
            "input_context": step.input_context,
            "status": "pending",
            "result": "",
        })

    return {
        "messages": [AIMessage(content=f"[Planning Agent] Plan ready with {len(action_checklist)} steps.")],
        "implementation_plan": result.implementation_plan,
        "action_checklist": action_checklist,
    }


# ── Build sub-graph ──────────────────────────────────────────────────

def build_planning_graph():
    graph = StateGraph(MainState)

    graph.add_node("planning_node", planning_node)
    graph.add_node("tools", ToolNode(all_planning_tools))

    graph.add_edge(START, "planning_node")
    graph.add_conditional_edges("planning_node", tools_condition)
    graph.add_edge("tools", "planning_node")

    return graph.compile()


planning_agent_graph = build_planning_graph()