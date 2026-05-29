"""Supervisor Agent — executes the plan by dispatching tasks to sub-agents.

Sub-graph flow:
  START → supervisor → [<agent> → supervisor (loop)] | FINISH → END

The supervisor owns BOTH decisions on every iteration:
  1. Which pending task to run next (dependency-aware).
  2. Which agent (from AGENT_REGISTRY) handles it.

The planner produces agent-agnostic tasks; the supervisor picks the agent
at dispatch time so adding a new agent never requires re-planning.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.agents.registry import AGENT_REGISTRY, registry_prompt
from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import MainState
from src.utils.errors import node_guard

logger = get_logger("agents.supervisor")

MAX_SUPERVISOR_ITERATIONS = 15
_FINISH = "FINISH"
_DEFAULT_AGENT = next(iter(AGENT_REGISTRY))


class SupervisorRoutingOutput(BaseModel):
    """LLM output for task + agent routing."""
    next_agent: str = Field(
        default=_FINISH,
        description=f"One of {list(AGENT_REGISTRY)} or 'FINISH' if all done",
    )
    next_task_id: str = Field(
        default="",
        description="The 'id' field of the task to dispatch (e.g. 'step_1')",
    )


def _dispatch(task: dict, agent: str, iteration: int) -> dict:
    return {
        "messages": [AIMessage(content=f"Supervisor: dispatching {task['id']} → {agent}")],
        "next_agent": agent,
        "current_task": task,
        "iteration": iteration,
    }


def _finish(reason: str, iteration: int) -> dict:
    logger.info("Supervisor: %s → FINISH", reason)
    return {
        "messages": [AIMessage(content=reason)],
        "next_agent": _FINISH,
        "iteration": iteration,
    }


def _route_via_llm(state: MainState, pending_tasks: list[dict]) -> SupervisorRoutingOutput:
    """Ask the LLM to pick the next task AND the agent to run it."""
    llm = llm_factory.create("GEMMA_4_31B", temperature=0, max_tokens=1024)
    structured_llm = llm.with_structured_output(SupervisorRoutingOutput)

    pending_summary = json.dumps(
        [{"id": t["id"], "desc": t.get("task_description", ""),
          "depends_on": t.get("depends_on", [])} for t in pending_tasks],
        indent=2,
    )
    completed_ids = [t["id"] for t in state.get("completed_tasks", [])]

    messages = [
        SystemMessage(content=load_prompt("supervisor_agent")),
        HumanMessage(content=(
            f"User Query: {state.get('user_query', '')}\n"
            f"Implementation Plan:\n{state.get('implementation_plan', '')}\n\n"
            f"Available Agents:\n{registry_prompt()}\n\n"
            f"Completed Task IDs: {completed_ids}\n"
            f"Pending Tasks:\n{pending_summary}\n\n"
            "Pick the next task to execute AND the best agent for it. "
            "`next_task_id` MUST be one of the pending IDs above. "
            f"`next_agent` MUST be one of {list(AGENT_REGISTRY)}."
        )),
    ]
    return structured_llm.invoke(messages)


@node_guard("supervisor", "supervisor_node")
def supervisor_node(state: MainState) -> dict:
    iteration = state.get("iteration", 0) + 1
    completed_ids = {t["id"] for t in state.get("completed_tasks", [])}
    pending_tasks = [t for t in state.get("action_checklist", []) if t["id"] not in completed_ids]

    if not pending_tasks:
        return _finish("All tasks completed successfully.", iteration)
    if iteration > MAX_SUPERVISOR_ITERATIONS:
        return _finish(f"Max iterations ({MAX_SUPERVISOR_ITERATIONS}) reached.", iteration)

    # Single agent + single task → skip the LLM call entirely.
    if len(pending_tasks) == 1 and len(AGENT_REGISTRY) == 1:
        return _dispatch(pending_tasks[0], _DEFAULT_AGENT, iteration)

    routing = _route_via_llm(state, pending_tasks)
    pending_by_id = {t["id"]: t for t in pending_tasks}
    chosen_task = pending_by_id.get(routing.next_task_id) or pending_tasks[0]
    chosen_agent = routing.next_agent if routing.next_agent in AGENT_REGISTRY else _DEFAULT_AGENT

    if routing.next_task_id not in pending_by_id:
        logger.warning("Supervisor: unknown task id '%s', falling back to '%s'",
                       routing.next_task_id, chosen_task["id"])
    if routing.next_agent not in AGENT_REGISTRY and routing.next_agent != _FINISH:
        logger.warning("Supervisor: unknown agent '%s', falling back to '%s'",
                       routing.next_agent, chosen_agent)

    return _dispatch(chosen_task, chosen_agent, iteration)


@node_guard("supervisor", "coding_agent_wrapper")
def coding_agent_wrapper(state: MainState) -> dict:
    """Invoke the coding sub-graph for the current task and mark it done."""
    from src.agents.codeagent import run_coding_node

    current_task = state["current_task"]
    result = run_coding_node(state)

    return {
        "messages": result.get("messages", [AIMessage(content="Task Completed Successfully")]),
        "completed_tasks": [current_task],
    }


@node_guard("supervisor", "research_agent_wrapper")
def research_agent_wrapper(state: MainState) -> dict:
    """Invoke the research sub-graph for the current task and mark it done."""
    from src.agents.researchagent import run_research_node

    current_task = state["current_task"]
    result = run_research_node(state)

    return {
        "messages": result.get("messages", [AIMessage(content="Research Completed Successfully")]),
        "completed_tasks": [current_task],
    }


AGENT_NODES = {
    "coding_agent": coding_agent_wrapper,
    "research_agent": research_agent_wrapper,
}


def route_after_supervisor(state: MainState) -> str:
    agent = state.get("next_agent", _FINISH)
    if agent in AGENT_NODES:
        return agent
    if agent != _FINISH:
        logger.warning("Supervisor: unknown agent '%s', finishing", agent)
    return _FINISH


def build_supervisor_graph():
    graph = StateGraph(MainState)
    graph.add_node("supervisor", supervisor_node)

    edge_map = {_FINISH: END}
    for agent_name, wrapper in AGENT_NODES.items():
        graph.add_node(agent_name, wrapper)
        graph.add_edge(agent_name, "supervisor")
        edge_map[agent_name] = agent_name

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor, edge_map)

    return graph.compile()


supervisor_agent_graph = build_supervisor_graph()
