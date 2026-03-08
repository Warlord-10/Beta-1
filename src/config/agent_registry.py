"""Agent registry — maps agent names to their compiled sub-graphs."""

from src.agents.fileagent import file_agent_graph
from src.agents.chatagent import chat_agent_graph
from src.agents.supervisoragent import supervisor_agent_graph
from src.agents.codeagent import code_agent_graph
from src.agents.systemagent import system_agent_graph
from src.agents.searchagent import search_agent_graph

AGENT_REGISTRY = {
    "CHAT_AGENT": chat_agent_graph,
    "FILE_AGENT": file_agent_graph,
    "CODE_AGENT": code_agent_graph,
    "SYSTEM_AGENT": system_agent_graph,
    "SEARCH_AGENT": search_agent_graph,
    "SUPERVISOR_AGENT": supervisor_agent_graph,
}