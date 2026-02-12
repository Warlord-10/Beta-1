"""File Agent — agent configuration and tool binding.

Tools are defined in `src/tools/file_tools/` and imported here.
This module re-exports the tool list so the graph can reference it
from a single, agent-scoped location.
"""

from src.tools.file_tools import file_tools as file_agent_tools

__all__ = ["file_agent_tools"]
