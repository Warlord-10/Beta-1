"""System tools — tools for the System Agent."""

from src.tools.system_tools.bash_exec import bash_exec
from src.tools.system_tools.git_ops import git_ops
from src.tools.system_tools.install_pkg import install_pkg
from src.tools.system_tools.env_vars import env_vars
from src.tools.system_tools.process_mgmt import process_mgmt

system_tools = [
    bash_exec,
    git_ops,
    install_pkg,
    env_vars,
    process_mgmt,
]

__all__ = [
    "system_tools",
    "bash_exec",
    "git_ops",
    "install_pkg",
    "env_vars",
    "process_mgmt",
]
