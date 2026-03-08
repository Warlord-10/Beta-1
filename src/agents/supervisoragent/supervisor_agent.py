"""Supervisor Agent — decompose, route, validate loop.

This module builds the supervisor sub-graph:
  supervisor_node → router_node → {agent} → validator_node → supervisor_node (loop)

The supervisor LLM produces a plan and drives the router via `next_agent`.
The validator checks each agent's result and emits a verdict.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated

from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from src.states.supervisor_state import SupervisorState, TaskItem
from src.states.agent_state import SubAgentState
from src.agents.supervisoragent.system_prompt import SUPERVISOR_AGENT_SYSTEM_PROMPT
from src.config.logger import get_logger

logger = get_logger("agents.supervisor")

MAX_SUPERVISOR_ITERATIONS = 15


def _get_llm():
    """Lazy LLM initialization."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        max_output_tokens=2048,
    )


def _get_agent_graph(agent_name: str):
    """Lazy import of agent graphs to avoid circular imports."""
    if agent_name == "file_agent":
        from src.agents.fileagent import file_agent_graph
        return file_agent_graph
    elif agent_name == "code_agent":
        from src.agents.codeagent import code_agent_graph
        return code_agent_graph
    elif agent_name == "system_agent":
        from src.agents.systemagent import system_agent_graph
        return system_agent_graph
    elif agent_name == "search_agent":
        from src.agents.searchagent import search_agent_graph
        return search_agent_graph
    else:
        raise ValueError(f"Unknown agent: {agent_name}")


# ── Helper ───────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


# ── Supervisor node ──────────────────────────────────────────────────

def supervisor_node(state: SupervisorState) -> dict:
    """Decompose the task into a plan or re-plan after validation."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=SUPERVISOR_AGENT_SYSTEM_PROMPT),
        *state["messages"],
    ]

    # Add context about current progress
    completed_ids = [t["id"] for t in state.get("completed", [])]
    pending_ids = [t.get("id", "?") for t in state.get("pending", [])]
    if completed_ids or pending_ids:
        progress_msg = HumanMessage(content=(
            f"Progress update:\n"
            f"  Completed tasks: {completed_ids}\n"
            f"  Pending tasks: {pending_ids}\n"
            f"  Last verdict: {state.get('verdict', 'none')}\n"
            f"Plan accordingly — assign next_agent or set next_agent to FINISH."
        ))
        messages.append(progress_msg)

    result = llm.invoke(messages)
    parsed = _parse_json(result.content)

    updates: dict = {
        "messages": [result],
        "iteration": state.get("iteration", 0) + 1,
    }

    # First call: build the plan
    if not state.get("plan"):
        plan_items = []
        for item in parsed.get("plan", []):
            plan_items.append(TaskItem(
                id=item.get("id", ""),
                description=item.get("description", ""),
                assigned_agent=item.get("assigned_agent", ""),
                context=item.get("context", {}),
                status="pending",
                result="",
            ))
        updates["plan"] = plan_items
        updates["pending"] = list(plan_items)

    updates["next_agent"] = parsed.get("next_agent", "FINISH")

    logger.info("Supervisor: next_agent=%s, iteration=%d",
                updates["next_agent"], updates["iteration"])
    return updates


# ── Agent wrapper nodes ──────────────────────────────────────────────

def _run_sub_agent(agent_name: str, state: SupervisorState) -> dict:
    """Invoke a sub-agent graph and collect its result."""
    graph = _get_agent_graph(agent_name)

    # Find current task from pending
    pending = state.get("pending", [])
    current_task = pending[0] if pending else TaskItem(
        id="adhoc", description=state.get("task", ""),
        assigned_agent="", context={}, status="working", result=""
    )

    # Build sub-agent input
    task_msg = HumanMessage(content=current_task["description"])
    agent_input = {
        "messages": [task_msg],
        "task": current_task,
        "status": "working",
        "result": "",
        "iterations": 0,
        "cwd": ".",
    }

    try:
        result = graph.invoke(agent_input)
        agent_result = result.get("result", "")
        if not agent_result and result.get("messages"):
            last_msg = result["messages"][-1]
            agent_result = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    except Exception as e:
        logger.error("Sub-agent error: %s", e)
        agent_result = f"Agent error: {e}"

    return {
        "messages": [AIMessage(content=f"[{agent_name}] Result for task '{current_task['id']}':\n{agent_result}")],
    }


def file_agent_node(state: SupervisorState) -> dict:
    return _run_sub_agent("file_agent", state)


def code_agent_node(state: SupervisorState) -> dict:
    return _run_sub_agent("code_agent", state)


def system_agent_node(state: SupervisorState) -> dict:
    return _run_sub_agent("system_agent", state)


def search_agent_node(state: SupervisorState) -> dict:
    return _run_sub_agent("search_agent", state)


# ── Validator node ───────────────────────────────────────────────────

def validator_node(state: SupervisorState) -> dict:
    """Check the quality of the last agent's result."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are a result validator. Check the agent's output for quality.\n"
            "Respond with JSON: {\"verdict\": \"approved\" or \"needs_revision\" or \"failed\", \"feedback\": \"...\"}\n"
            "Approve if the result adequately addresses the task. "
            "Mark needs_revision if the output is partially wrong. "
            "Mark failed if the output is completely wrong or the agent errored."
        )),
        *state["messages"][-3:],  # last few messages for context
    ]

    result = llm.invoke(messages)
    parsed = _parse_json(result.content)

    verdict = parsed.get("verdict", "approved")
    feedback = parsed.get("feedback", "")

    logger.info("Validator verdict: %s — %s", verdict, feedback[:100])

    # Move task from pending to completed if approved
    pending = list(state.get("pending", []))
    completed = list(state.get("completed", []))

    if pending and verdict == "approved":
        done_task = dict(pending.pop(0))
        done_task["status"] = "done"
        completed.append(done_task)

    return {
        "verdict": verdict,
        "pending": pending,
        "completed": completed,
        "messages": [AIMessage(content=f"[Validator] {verdict}: {feedback}")],
    }


# ── Routing logic ────────────────────────────────────────────────────

def route_to_agent(state: SupervisorState) -> str:
    """Route based on next_agent field."""
    agent = state.get("next_agent", "FINISH")
    if agent in ("file_agent", "code_agent", "system_agent", "search_agent"):
        return agent
    return "FINISH"


def after_validation(state: SupervisorState) -> str:
    """After validation, decide whether to loop or finish."""
    if state.get("iteration", 0) >= MAX_SUPERVISOR_ITERATIONS:
        return "FINISH"
    verdict = state.get("verdict", "approved")
    pending = state.get("pending", [])

    if verdict == "needs_revision":
        return "supervisor"  # re-plan
    if verdict == "failed":
        return "supervisor"  # re-plan with failure context
    if not pending:
        return "FINISH"      # all done
    return "supervisor"      # next task


# ── Build graph ──────────────────────────────────────────────────────

def build_supervisor_graph():
    graph = StateGraph(SupervisorState)

    # Nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("file_agent", file_agent_node)
    graph.add_node("code_agent", code_agent_node)
    graph.add_node("system_agent", system_agent_node)
    graph.add_node("search_agent", search_agent_node)
    graph.add_node("validator", validator_node)

    # Entry
    graph.add_edge(START, "supervisor")

    # Supervisor → Router → Agent
    graph.add_conditional_edges("supervisor", route_to_agent, {
        "file_agent": "file_agent",
        "code_agent": "code_agent",
        "system_agent": "system_agent",
        "search_agent": "search_agent",
        "FINISH": END,
    })

    # Each agent → Validator
    graph.add_edge("file_agent", "validator")
    graph.add_edge("code_agent", "validator")
    graph.add_edge("system_agent", "validator")
    graph.add_edge("search_agent", "validator")

    # Validator → Supervisor (loop) or FINISH
    graph.add_conditional_edges("validator", after_validation, {
        "supervisor": "supervisor",
        "FINISH": END,
    })

    return graph.compile()


supervisor_agent_graph = build_supervisor_graph()
