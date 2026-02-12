"""Tool: write_file — Create or overwrite a file with content."""

import os

from langchain_core.tools import tool


@tool
def write_file(file_path: str, content: str, overwrite: bool = False) -> str:
    """Create or overwrite a file with the given content.

    Args:
        file_path: Absolute or relative path to the file to write.
        content: The text content to write into the file.
        overwrite: Whether to overwrite the file if it exists.

    Returns:
        A confirmation message.
    """
    try:
        abs_path = os.path.abspath(file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w" if overwrite else "x", encoding="utf-8") as f:
            f.write(content)
        return f"✅ Successfully wrote to `{abs_path}` ({len(content)} characters)."
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error writing file `{file_path}`: {e}"