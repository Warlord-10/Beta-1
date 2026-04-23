"""Supervisor Agent — executes the plan by dispatching tasks to sub-agents.

Sub-graph flow:
  supervisor_node → route → coding_wrapper (invokes coding_agent_graph)
                          → task_done → supervisor_node (loop)
                          → FINISH → END

The supervisor picks the next pending task, invokes the appropriate
agent sub-graph as a black box, marks the task complete, and loops.
No validator/review node — kept simple for the prototype.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import MainState

logger = get_logger("agents.supervisor")

MAX_SUPERVISOR_ITERATIONS = 15


class SupervisorRoutingOutput(BaseModel):
    """LLM output for task routing."""
    next_agent: str = Field(
        default="FINISH",
        description="Which agent to route to (e.g. 'coding_agent'), or 'FINISH' if all done"
    )
    next_task_id: str = Field(
        default="",
        description="The 'id' field of the task to dispatch (e.g. 'step_1')"
    )


def supervisor_node(state: MainState) -> dict:

    action_checklist = state.get("action_checklist", [])
    iteration = state.get("iteration", 0) + 1
    completed_task_ids = {t["id"] for t in state.get("completed_tasks", [])}
    pending_tasks = [t for t in action_checklist if t["id"] not in completed_task_ids]

    if not pending_tasks:
        logger.info("Supervisor: All tasks completed → FINISH")
        return {
            "messages": [AIMessage(content="All tasks completed successfully.")],
            "next_agent": "FINISH",
            "iteration": iteration,
        }

    if iteration > MAX_SUPERVISOR_ITERATIONS:
        logger.warning("Supervisor: Max iterations (%d) reached → FINISH", MAX_SUPERVISOR_ITERATIONS)
        return {
            "messages": [AIMessage(content="Max iterations reached. Finishing with completed work.")],
            "next_agent": "FINISH",
            "iteration": iteration,
        }

    # For single pending task, skip the LLM call entirely
    if len(pending_tasks) == 1:
        next_task = pending_tasks[0]
        agent = next_task.get("assigned_agent", "coding_agent")
        logger.info("Supervisor: single pending task %s → %s (iteration %d)",
                     next_task["id"], agent, iteration)
        return {
            "messages": [AIMessage(content=f"Supervisor: dispatching task {next_task['id']} to {agent}")],
            "next_agent": agent,
            "current_task": next_task,
            "iteration": iteration,
        }

    # Multiple pending tasks — use LLM to pick next (respects dependencies)
    system_prompt = load_prompt("supervisor_agent")

    llm = llm_factory.create("GEMMA_4_31B", temperature=0, max_tokens=1024)
    structured_llm = llm.with_structured_output(SupervisorRoutingOutput)

    system_messages = [
        SystemMessage(content=system_prompt),
        SystemMessage(content=f"""
        - User Query: {state.get('user_query', 'No query available.')}
        - Implementation Plan: {state.get('implementation_plan', 'No plan available.')}
        - Completed Task IDs: {list(completed_task_ids)}
        - Pending Tasks: {pending_tasks}

        TASK: Pick the next task to execute based on the implementation plan. You MUST set current_task_id to one of the pending task IDs listed above.
        """)
    ]

    result: SupervisorRoutingOutput = structured_llm.invoke(messages=system_messages + state.get("messages", []))

    if result.next_task_id not in [t["id"] for t in pending_tasks]:
        logger.error("Supervisor: LLM returned unknown task ID '%s', falling back to '%s'",
                        result.next_task_id, pending_tasks[0]["id"])
        return {
            "messages": [AIMessage(content=f"Supervisor: dispatching task {pending_tasks[0]['id']} to {pending_tasks[0]['assigned_agent']}")],
            "next_agent": pending_tasks[0]['assigned_agent'],
            "current_task": pending_tasks[0],
            "iteration": iteration,
        }
    
    # Find the matched task
    next_task = None
    for task in pending_tasks:
        if task["id"] == result.next_task_id:
            next_task = task
            break
    
    return {
        "messages": [AIMessage(content=f"Supervisor: dispatching task {next_task['id']} to {next_task['assigned_agent']}")],
        "next_agent": next_task['assigned_agent'],
        "current_task": next_task,
        "iteration": iteration+1,
    }


def coding_agent_wrapper(state: MainState) -> dict:
    from src.agents.codeagent import coding_agent_graph

    logger.info("Invoking coding agent for task: %s", state.get("current_task", {}).get("id", "?"))

    result = coding_agent_graph.invoke({
        "current_task": state["current_task"],
        "messages": [],
        "completed_tasks": state["completed_tasks"],
        "cwd": state["cwd"],
    })

    result_messages = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            result_messages.append(msg)

    if not result_messages:
        result_messages = result.get("messages", [])[-1:]

    # Mark the current task as completed
    completed_task = state.get("current_task")
    completed_task["status"] = "done"
    completed_task["result"] = result_messages[-1].content

    return {
        "messages": result_messages,
        "completed_tasks": [completed_task],
    }


def after_agent(state: MainState) -> dict:
    """After an agent finishes a task, mark it as completed."""
    current_task = state.get("current_task", {})

    if current_task:
        current_task["status"] = "done"
        current_task["result"] = state["messages"][-1].content
        return {completed_tasks: [current_task]}

    return {}


def route_after_supervisor(state: MainState) -> str:
    """Route: to an agent or FINISH."""
    agent = state.get("next_agent", "FINISH")
    if agent == "coding_agent":
        return "coding_agent"
    if agent == "FINISH":
        return "FINISH"

    logger.warning("Supervisor: unknown agent '%s', finishing", agent)
    return "FINISH"


# ── Build sub-graph ──────────────────────────────────────────────────

def build_supervisor_graph():
    graph = StateGraph(MainState)

    # Nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("coding_agent", coding_agent_wrapper)
    # graph.add_node("task_done", after_agent)

    # Entry
    graph.add_edge(START, "supervisor")

    graph.add_conditional_edges("supervisor", route_after_supervisor, {
        "coding_agent": "coding_agent",
        "FINISH": END,
    })

    graph.add_edge("coding_agent", "supervisor")

    # graph.add_edge("task_done", "supervisor")

    return graph.compile()


supervisor_agent_graph = build_supervisor_graph()
