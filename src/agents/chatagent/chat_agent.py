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

# Memory tools
from src.tools.memory_tools.daily_memory_tools import (
    add_to_daily_memory,
    read_daily_memory
)


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
    return f"DELEGATED: {task_summary}"


# ── Tool list for the chat agent ─────────────────────────────────────

CHAT_AGENT_TOOLS = [
    # File tools
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    safe_bash,

    # Core delegate tool
    delegate_to_planner,

    # Scheduler tools
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task,

    # Memory tools
    add_to_daily_memory,
    read_daily_memory,
]

    
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
            system_prompt = self.system_prompt,
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
