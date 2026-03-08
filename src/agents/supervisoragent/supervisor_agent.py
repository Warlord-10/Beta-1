from __future__ import annotations

import operator
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langchain.agents import AgentState

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agents.supervisoragent.system_prompt import SUPERVISOR_AGENT_SYSTEM_PROMPT

class SupervisorAgentState(AgentState):
    messages: Annotated[list[AnyMessage], operator.add]
    task_queue: list[dict[str, any]]
    task_updates: list[dict[str, any]]


def build_supervisor_agent_graph():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=1,
        max_output_tokens=250,
    )

    graph = create_agent(
        model=llm,
        system_prompt=SUPERVISOR_AGENT_SYSTEM_PROMPT,
        state_schema=SupervisorAgentState,
    )

    return graph


# Pre-built graph instance for convenience
supervisor_agent_graph = build_supervisor_agent_graph()
