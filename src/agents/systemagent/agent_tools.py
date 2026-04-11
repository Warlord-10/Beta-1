"""System Agent — agent configuration and tool binding.

Combines system tools (bash, git, packages, env, processes)
with file tools (read, write, list, search, delete, etc.)
"""

from src.tools.system_tools import system_tools as system_agent_tools
from src.tools.file_tools import file_tools

__all__ = ["system_agent_tools", "file_tools"]
