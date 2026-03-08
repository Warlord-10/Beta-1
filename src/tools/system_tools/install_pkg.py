"""Tool: install_pkg — Install a package using a package manager."""

import subprocess

from langchain_core.tools import tool


@tool
def install_pkg(package: str, manager: str = "pip") -> str:
    """Install a package using the specified package manager.

    Args:
        package: Name of the package to install.
        manager: Package manager to use ("pip", "uv", "npm", "brew"). Defaults to "pip".

    Returns:
        Installation output or error description.
    """
    manager_cmds = {
        "pip": f"pip install {package}",
        "uv": f"uv add {package}",
        "npm": f"npm install {package}",
        "brew": f"brew install {package}",
    }

    if manager not in manager_cmds:
        return f"❌ Unsupported package manager: `{manager}`. Supported: {', '.join(manager_cmds)}"

    cmd = manager_cmds[manager]
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return f"✅ Installed `{package}` via {manager}.\n{output.strip()}"
        else:
            return f"❌ Failed to install `{package}` via {manager}:\n{output.strip()}"
    except subprocess.TimeoutExpired:
        return f"❌ Installation of `{package}` timed out."
    except Exception as e:
        return f"❌ Error installing `{package}`: {e}"
