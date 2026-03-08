from src.agents.fileagent import file_agent_graph
from src.agents.chatagent import chat_agent_graph
from src.agents.supervisoragent import supervisor_agent_graph

AGENT_REGISTRY = {
    "FILE_AGENT": file_agent_graph,
    "CHAT_AGENT": chat_agent_graph,
    "SUPERVISOR_AGENT": supervisor_agent_graph,
}