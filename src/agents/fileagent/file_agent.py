"""LangGraph graph definition for the File Management Agent.

This agent uses a ReAct loop with access to a current working directory (cwd)
that persists across conversation turns.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langchain.agents import AgentState
from langchain.messages import SystemMessage

from src.agents.fileagent.agent_tools import file_agent_tools
from src.agents.fileagent.system_prompt import FILE_AGENT_SYSTEM_PROMPT

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langgraph.runtime import Runtime
from typing import Any, Callable



class FileAgentState(AgentState):
    """State for the file agent sub-graph."""
    messages: Annotated[list[AnyMessage], operator.add]
    cwd: str
    current_task: str = None

class FileAgentMiddleware(AgentMiddleware):
    """Middleware for the file agent sub-graph."""

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        context_message = SystemMessage("Current working directory: " + state["cwd"])
        state["messages"].append(context_message)
        return state

    # def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    #     last_message = state["messages"][-1]
    #     if hasattr(last_message, "tool_calls"):
    #         for tool_call in last_message.tool_calls:
    #             if tool_call["name"] == "change_directory":
    #                 state["cwd"] = tool_call["args"]["path"]
    #     return state
        


def build_file_agent_graph():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=1,
        max_output_tokens=250,
    )

    graph = create_agent(
        model=llm,
        tools=file_agent_tools,
        system_prompt=FILE_AGENT_SYSTEM_PROMPT,
        state_schema=FileAgentState,
        middleware=[FileAgentMiddleware()],
    )


    return graph


# Pre-built graph instance for convenience
file_agent_graph = build_file_agent_graph()
