"""Tool: read_file — Read the contents of a file."""

import os

from langchain_core.tools import tool


@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file.

    Args:
        file_path: Absolute or relative path to the file to read.

    Returns:
        The contents of the file as a string.
    """
    try:
        abs_path = os.path.abspath(file_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"📄 Contents of `{abs_path}`:\n\n{content}"
    except FileNotFoundError:
        return f"❌ Error: File not found — `{file_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error reading file `{file_path}`: {e}"
