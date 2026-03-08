"""Tool: debug_code — Analyse code for potential bugs and issues."""

import os

from langchain_core.tools import tool


@tool
def debug_code(file_path: str) -> str:
    """Read a code file and return its contents for debugging analysis.

    The LLM will analyse the code for bugs — this tool just provides the
    source content so the agent can reason over it.

    Args:
        file_path: Absolute or relative path to the file to debug.

    Returns:
        The file contents prefixed with metadata, or an error description.
    """
    try:
        abs_path = os.path.abspath(file_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.count("\n") + 1
        return (
            f"🔍 Debug target: `{abs_path}` ({lines} lines)\n\n"
            f"```\n{content}\n```"
        )
    except FileNotFoundError:
        return f"❌ Error: File not found — `{file_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error reading `{file_path}`: {e}"
