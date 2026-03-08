"""Chat Agent — entry-point classifier.

Classifies user queries as simple or complex:
  - Simple  → returns a direct response
  - Complex → passes task to the supervisor agent

Uses structured output (JSON) to emit { complexity, response, task_summary }.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from src.agents.chatagent.system_prompt import CHAT_AGENT_SYSTEM_PROMPT
from src.config.logger import get_logger

logger = get_logger("agents.chat_agent")


class ChatAgentState(TypedDict):
    """Internal state for the chat agent node."""
    messages: Annotated[list[AnyMessage], operator.add]
    complexity: str        # "simple" | "complex"
    response: str          # direct response for simple queries
    task_summary: str      # task description for complex queries


def _get_llm():
    """Lazy LLM initialization — avoids module-level API key validation."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        max_output_tokens=1024,
    )


def classify_node(state: ChatAgentState) -> dict:
    """Classify the user query using the LLM."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=CHAT_AGENT_SYSTEM_PROMPT),
        *state["messages"],
    ]

    result = llm.invoke(messages)
    raw = result.content.strip()

    # Parse the JSON response
    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Chat agent returned non-JSON, treating as simple: %s", raw[:200])
        parsed = {"complexity": "simple", "response": raw, "task_summary": ""}

    complexity = parsed.get("complexity", "simple")
    response = parsed.get("response", "")
    task_summary = parsed.get("task_summary", "")

    logger.info("Classified as %s: %s", complexity, task_summary or response[:100])

    return {
        "complexity": complexity,
        "response": response,
        "task_summary": task_summary,
        "messages": [AIMessage(content=response)] if complexity == "simple" else [],
    }


def format_response_node(state: ChatAgentState) -> dict:
    """Format the final response to the user (called after supervisor finishes)."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are Beta-1. The task has been completed by your team of agents. "
            "Below are the results. Provide a clear, well-formatted final response to the user. "
            "Be concise but thorough."
        )),
        *state["messages"],
    ]
    result = llm.invoke(messages)
    return {
        "messages": [result],
        "response": result.content,
    }


def build_chat_agent_graph():
    graph = StateGraph(ChatAgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("format_response", format_response_node)

    graph.add_edge(START, "classify")
    graph.add_edge("classify", END)
    graph.add_edge("format_response", END)

    return graph.compile()


chat_agent_graph = build_chat_agent_graph()
