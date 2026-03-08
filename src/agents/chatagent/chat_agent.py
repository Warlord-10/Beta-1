from __future__ import annotations

import operator
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langchain.agents import AgentState

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agents.chatagent.system_prompt import CHAT_AGENT_SYSTEM_PROMPT

class ChatAgentState(AgentState):
    messages: Annotated[list[AnyMessage], operator.add]
    
class ChatAgentOutput(TypedDict):
    response: str
    is_supervised: bool
    supervisor_message: str
    
def build_chat_agent_graph():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=1,
        max_output_tokens=250,
    )

    graph = create_agent(
        model=llm,
        system_prompt=CHAT_AGENT_SYSTEM_PROMPT,
        state_schema=ChatAgentState,
        response_format=ChatAgentOutput
    )

    return graph


# Pre-built graph instance for convenience
chat_agent_graph = build_chat_agent_graph()
