"""Tool: process_mgmt — List or manage running processes."""

import subprocess

from langchain_core.tools import tool


@tool
def process_mgmt(action: str, pid: int = 0, query: str = "") -> str:
    """Manage system processes.

    Args:
        action: "list" to list processes, "kill" to terminate a process, "find" to search.
        pid: Process ID (required for "kill").
        query: Search string (required for "find").

    Returns:
        Process listing, confirmation, or error description.
    """
    if action == "list":
        try:
            result = subprocess.run(
                "ps aux --sort=-%mem | head -20",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            return f"📋 Top processes:\n{result.stdout}"
        except Exception as e:
            return f"❌ Error listing processes: {e}"

    elif action == "find":
        if not query:
            return "❌ 'query' is required for action='find'."
        try:
            result = subprocess.run(
                f"ps aux | grep -i '{query}' | grep -v grep",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            return f"🔍 Processes matching '{query}':\n{output}" if output else f"No processes matching '{query}'."
        except Exception as e:
            return f"❌ Error finding processes: {e}"

    elif action == "kill":
        if pid <= 0:
            return "❌ A valid 'pid' is required for action='kill'."
        try:
            import signal
            os_import = __import__("os")
            os_import.kill(pid, signal.SIGTERM)
            return f"✅ Sent SIGTERM to process {pid}."
        except ProcessLookupError:
            return f"❌ No process with PID {pid}."
        except PermissionError:
            return f"❌ Permission denied — cannot kill PID {pid}."
        except Exception as e:
            return f"❌ Error killing process {pid}: {e}"

    else:
        return f"❌ Unknown action `{action}`. Use 'list', 'find', or 'kill'."
