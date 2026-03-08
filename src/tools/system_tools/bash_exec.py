"""Tool: bash_exec — Execute a shell command."""

import subprocess

from langchain_core.tools import tool


@tool
def bash_exec(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return its output.

    Args:
        command: The shell command to execute.
        timeout: Max seconds to wait before killing the process. Defaults to 30.

    Returns:
        Combined stdout and stderr output, or an error description.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += f"stdout:\n{result.stdout}\n"
        if result.stderr:
            output += f"stderr:\n{result.stderr}\n"
        if result.returncode != 0:
            output += f"⚠️ Exit code: {result.returncode}\n"
        return output.strip() or "✅ Command completed with no output."
    except subprocess.TimeoutExpired:
        return f"❌ Error: Command timed out after {timeout}s — `{command}`"
    except Exception as e:
        return f"❌ Error executing command: {e}"
