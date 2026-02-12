"""Tool: create_directory — Create a new directory."""

import os

from langchain_core.tools import tool


@tool
def create_directory(directory_path: str) -> str:
    """Create a new directory (including any necessary parent directories).

    Args:
        directory_path: Absolute or relative path of the directory to create.

    Returns:
        A confirmation message.
    """
    try:
        abs_path = os.path.abspath(directory_path)
        os.makedirs(abs_path, exist_ok=True)
        return f"✅ Directory created: `{abs_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{directory_path}`"
    except Exception as e:
        return f"❌ Error creating directory `{directory_path}`: {e}"
