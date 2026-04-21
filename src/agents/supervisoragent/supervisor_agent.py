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
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from src.llms import llm_factory
from src.states.main_state import MainState
from src.prompts import load_prompt
from src.config.logger import get_logger

logger = get_logger("agents.supervisor")

MAX_SUPERVISOR_ITERATIONS = 15


# ── Structured output schema ────────────────────────────────────────

class SupervisorRoutingOutput(BaseModel):
    """LLM output for task routing."""
    next_agent: str = Field(
        default="FINISH",
        description="Which agent to route to (e.g. 'coding_agent'), or 'FINISH' if all done"
    )
    current_task_id: str = Field(
        default="",
        description="The 'id' field of the task to dispatch (e.g. 'step_1')"
    )


# ── Supervisor node ──────────────────────────────────────────────────

def supervisor_node(state: MainState) -> dict:
    """Pick the next pending task and route to the appropriate agent."""
    action_checklist = state.get("action_checklist", [])
    completed_ids = {t["id"] for t in state.get("completed_tasks", [])}
    iteration = state.get("iteration", 0) + 1

    # Find pending tasks
    pending_tasks = [t for t in action_checklist if t["id"] not in completed_ids]

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

    llm = llm_factory.create("GEMINI_FLASH", temperature=0, max_tokens=1024)
    structured_llm = llm.with_structured_output(SupervisorRoutingOutput)

    # Format pending tasks clearly for the LLM
    tasks_text = "\n".join(
        f"  - id: {t['id']}, agent: {t['assigned_agent']}, description: {t['task_description']}"
        for t in pending_tasks
    )

    routing_prompt = f"""{system_prompt}

Implementation Plan:
{state.get('implementation_plan', 'No plan available.')}

Pending Tasks:
{tasks_text}

Completed Task IDs: {list(completed_ids)}

Pick the next task to execute. You MUST set current_task_id to one of the pending task IDs listed above."""

    result: SupervisorRoutingOutput = structured_llm.invoke(routing_prompt)

    # Find the matched task
    next_task = None
    for task in pending_tasks:
        if task["id"] == result.current_task_id:
            next_task = task
            break

    # Fallback: just take the first pending task if LLM returned bad ID
    if next_task is None:
        next_task = pending_tasks[0]
        logger.warning("Supervisor: LLM returned unknown task ID '%s', falling back to '%s'",
                        result.current_task_id, next_task["id"])

    agent = next_task.get("assigned_agent", result.next_agent)

    logger.info("Supervisor: routing to %s for task %s (iteration %d)",
                agent, next_task["id"], iteration)

    return {
        "messages": [AIMessage(content=f"Supervisor: dispatching task {next_task['id']} to {agent}")],
        "next_agent": agent,
        "current_task": next_task,
        "iteration": iteration,
    }


# ── Agent wrapper nodes ──────────────────────────────────────────────

def coding_agent_wrapper(state: MainState) -> dict:
    """Invoke the coding agent sub-graph as a black box."""
    from src.agents.codeagent import coding_agent_graph

    logger.info("Invoking coding agent for task: %s", state.get("current_task", {}).get("id", "?"))

    result = coding_agent_graph.invoke(state)

    # Extract the meaningful messages from the coding agent's work
    # Keep the last few messages that contain actual results
    result_messages = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            result_messages.append(msg)

    # If no clean AI messages, take the last message
    if not result_messages:
        result_messages = result.get("messages", [])[-1:]

    return {
        "messages": result_messages,
    }


def after_agent(state: MainState) -> dict:
    """After an agent finishes a task, mark it as completed."""
    current_task = state.get("current_task", {})

    if current_task:
        # Extract result from the last non-tool AI message
        result_content = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                result_content = msg.content
                break

        completed_task = {
            **current_task,
            "status": "done",
            "result": result_content[:2000],  # Cap result size
        }

        logger.info("Task %s completed", current_task.get("id", "unknown"))

        return {
            "completed_tasks": [completed_task],
        }

    return {}


# ── Routing logic ────────────────────────────────────────────────────

def route_after_supervisor(state: MainState) -> str:
    """Route: to an agent or FINISH."""
    agent = state.get("next_agent", "FINISH")
    if agent == "coding_agent":
        return "coding_agent"
    # Future: add system_agent, search_agent, etc.
    if agent == "FINISH":
        return "FINISH"
    # Unknown agent — log warning and finish
    logger.warning("Supervisor: unknown agent '%s', finishing", agent)
    return "FINISH"


# ── Build sub-graph ──────────────────────────────────────────────────

def build_supervisor_graph():
    graph = StateGraph(MainState)

    # Nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("coding_agent", coding_agent_wrapper)
    graph.add_node("task_done", after_agent)

    # Entry
    graph.add_edge(START, "supervisor")

    # Supervisor → route to agent or FINISH
    graph.add_conditional_edges("supervisor", route_after_supervisor, {
        "coding_agent": "coding_agent",
        "FINISH": END,
    })

    # Agent → mark task done
    graph.add_edge("coding_agent", "task_done")

    # Task done → back to supervisor for next task
    graph.add_edge("task_done", "supervisor")

    return graph.compile()


supervisor_agent_graph = build_supervisor_graph()
