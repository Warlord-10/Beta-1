"""Tool: change_directory — Change the current working directory."""

import os

from langchain_core.tools import tool


@tool
def change_directory(path: str) -> str:
    """Change the current working directory to the given path.

    Args:
        path: Absolute or relative path to navigate to.

    Returns:
        A confirmation message with the new absolute path.
    """
    try:
        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            return f"❌ Error: Not a directory — `{abs_path}`"

        return f"📂 Changed directory to: `{abs_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{path}`"
    except Exception as e:
        return f"❌ Error changing directory to `{path}`: {e}"
