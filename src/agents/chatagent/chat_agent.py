"""Chat Agent — primary user interface with tool-calling capabilities.

Architecture:
  This agent is the FIRST node in the main workflow graph.
  It receives user input and decides:
    1. Answer directly (greetings, general knowledge)
    2. Use tools (read files, list dirs, run safe commands)
    3. Delegate to planner (complex tasks needing code writing, multi-step ops)

Exports:
    chat_agent_node   — main entry node for the workflow
    format_response_node — formats results after complex task execution
"""

from __future__ import annotations

from pprint import pprint
from typing import Annotated, TypedDict, AsyncGenerator
import asyncio

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AIMessageChunk
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.states.main_state import MainState

# Read-only file tools
from src.tools.file_tools import (get_file_info, list_directory, read_file,
                                  search_content, search_files)

# Scheduler tools
from src.tools.scheduler_tools import (create_scheduled_task,
                                       delete_scheduled_task,
                                       list_scheduled_tasks,
                                       modify_scheduled_task,
                                       toggle_scheduled_task)

# Safe system tools
from src.tools.system_tools.safe_bash import safe_bash

logger = get_logger("agents.chat_agent")


# ── Delegation tool ─────────────────────────────────────────────────

@tool
def delegate_to_planner(task_summary: str) -> str:
    """Delegate a complex task to the planning agent.

    Call this when the user's request needs code writing, file modifications,
    multi-step operations, package installation, or other complex work that
    goes beyond reading/inspecting.

    Args:
        task_summary: A clear, detailed summary of what the user wants done.

    Returns:
        A confirmation string (routing is handled by the workflow graph).
    """
    return f"DELEGATE: {task_summary}"


# ── Tool list for the chat agent ─────────────────────────────────────

CHAT_AGENT_TOOLS = [
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    safe_bash,
    create_scheduled_task,
    modify_scheduled_task,
    toggle_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    delegate_to_planner,
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task
]



# ── Node functions ───────────────────────────────────────────────────

def chat_agent_node(state: MainState) -> dict:
    """Primary entry point — tool-calling chat agent.

    Handles the user query by:
    - Answering directly for simple queries
    - Using tools for read/inspect tasks
    - Calling delegate_to_planner for complex tasks
    """
    system_prompt = load_prompt("chat_agent")
    llm = llm_factory.create("OR_GEMMA4", temperature=0.7, max_tokens=1024 * 4)

    # Build the react agent
    agent = create_agent(
        model=llm,
        tools=CHAT_AGENT_TOOLS,
        system_prompt=system_prompt
    )

    # Invoke the agent with the full message history
    result = agent.invoke({"messages": state["messages"]})
    print(result)

    response_messages = result.get("messages", [])

    # Check if the agent decided to delegate
    delegated = False
    task_summary = ""

    for msg in response_messages:
        if hasattr(msg, "content") and isinstance(msg.content, str):
            if msg.content.startswith("DELEGATE:"):
                delegated = True
                task_summary = msg.content[len("DELEGATE:"):]
                break

    if delegated:
        logger.info("Chat agent delegating to planner: %s", task_summary[:100])
        return {
            "complexity": "complex",
            "user_query": task_summary,
            "final_response": "",
        }

    # Extract the final AI response (last AI message)
    final_text = ""
    for msg in reversed(response_messages):
        if isinstance(msg, AIMessage) and msg.content:
            final_text = msg.content
            break

    logger.info("Chat agent handled directly (%d chars)", len(final_text))

    return {
        "complexity": "simple",
        "messages": [AIMessage(content=final_text)] if final_text else [],
        "final_response": final_text,
    }


def format_response_node(state: MainState) -> dict:
    """Format complex task results into a polished user-facing response.

    Called after planning → supervisor completes a complex task.
    Builds context from completed_tasks and creates a final response.
    """
    system_prompt = load_prompt("chat_agent")

    llm = llm_factory.create("GEMINI_FLASH", temperature=0, max_tokens=1024 * 4)

    # Build context from completed tasks — this is reliable and not truncated
    user_query = state.get("user_query", "")
    completed_tasks = state.get("completed_tasks", [])

    task_results = []
    for task in completed_tasks:
        task_results.append(
            f"### Task: {task.get('task_description', 'Unknown')}\n"
            f"**Status**: {task.get('status', 'unknown')}\n"
            f"**Result**: {task.get('result', 'No result')}\n"
        )

    context = "\n---\n".join(task_results) if task_results else "No task results available."

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"User's original request: {user_query}"),
        AIMessage(content=f"Here are the results from the agent team:\n\n{context}"),
        HumanMessage(content="Please format a clear, helpful response for the user based on these results."),
    ]

    result = llm.invoke(messages)

    logger.info("Chat agent: formatted complex response (%d chars)", len(result.content))

    return {
        "messages": [result],
        "final_response": result.content,
    }


def chat(user_input: str, config: dict) -> None:
    if user_input.strip() == "":
        return

    system_prompt = load_prompt("chat_agent")
    llm = llm_factory.create("OR_GEMMA4", temperature=0.7, max_tokens=1024 * 4)

    # Build the react agent
    agent = create_agent(
        model=llm,
        tools=CHAT_AGENT_TOOLS,
        system_prompt=system_prompt,
        checkpointer=checkpointer
    )

    result = agent.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
        },
        config=config
    )

    pprint(result)
    response_messages = result.get("messages", [])

    return response_messages
    
class ChatAgent:
    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        self.state = MainState
        self.system_prompt = load_prompt("chat_agent")
        self.llm = llm_factory.create("GEMMA_4_31B", temperature=0.7, max_tokens=1024 * 4)

        self.agent = create_agent(
            model = self.llm,
            tools = CHAT_AGENT_TOOLS,
            # system_prompt = self.system_prompt,
            checkpointer=self.checkpointer,
            state_schema=self.state
        )

    def chat(self, user_input):
        result = self.agent.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_query": user_input,
                "complexity": "",
                "implementation_plan": "",
                "action_checklist": [],
                "current_task": {},
                "completed_tasks": [],
                "final_response": "",
                "cwd": "/",
                "iteration": 0,
                "next_agent": "",
            },
            config=self.config,
        )

        pprint(result)
        return result

    def stream(self, user_input):
        result = self.agent.stream(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_query": user_input,
                "complexity": "",
                "implementation_plan": "",
                "action_checklist": [],
                "current_task": {},
                "completed_tasks": [],
                "final_response": "",
                "cwd": "/",
                "iteration": 0,
                "next_agent": "",
            },
            config=self.config,
            stream_mode = "messages",
            version="v2"
        )

        for chunk in result:
            if chunk.get("type", None) == "messages":
                token, metadata = chunk.get("data", None)
                if isinstance(token, AIMessageChunk) and isinstance(token.content, str):
                    yield token.content
