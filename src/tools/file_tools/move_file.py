"""Tool: move_file — Move or rename a file or directory."""

import os
import shutil

from langchain_core.tools import tool


@tool
def move_file(source_path: str, destination_path: str) -> str:
    """Move or rename a file or directory.

    Args:
        source_path: The current path of the file or directory.
        destination_path: The new path for the file or directory.

    Returns:
        A confirmation message.
    """
    try:
        abs_source = os.path.abspath(source_path)
        abs_dest = os.path.abspath(destination_path)
        os.makedirs(os.path.dirname(abs_dest), exist_ok=True)
        shutil.move(abs_source, abs_dest)
        return f"✅ Moved `{abs_source}` → `{abs_dest}`"
    except FileNotFoundError:
        return f"❌ Error: Source not found — `{source_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied."
    except Exception as e:
        return f"❌ Error moving `{source_path}`: {e}"
