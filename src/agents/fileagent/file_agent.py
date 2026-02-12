"""LangGraph graph definition for the File Management Agent."""

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from src.agents.fileagent.agent_tools import file_agent_tools
from src.agents.fileagent.system_prompt import FILE_AGENT_SYSTEM_PROMPT


def build_file_agent_graph():
    """Build and return the compiled LangGraph for the file agent.

    The graph uses a ReAct (Reason + Act) loop:
        1. The LLM receives the user message + system prompt.
        2. It decides which tool(s) to call.
        3. Tool results are fed back to the LLM.
        4. The LLM produces a final human-readable response.

    Returns:
        A compiled LangGraph `CompiledGraph` ready for `.invoke()` or `.stream()`.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
    )

    graph = create_react_agent(
        model=llm,
        tools=file_agent_tools,
        prompt=FILE_AGENT_SYSTEM_PROMPT,
    )

    return graph


# Pre-built graph instance for convenience
file_agent_graph = build_file_agent_graph()
