"""Tool: list_directory — List the contents of a directory."""

import os

from langchain_core.tools import tool

from src.tools.file_tools._helpers import format_size


@tool
def list_directory(directory_path: str) -> str:
    """List the contents of a directory.

    Args:
        directory_path: Absolute or relative path to the directory.

    Returns:
        A formatted string listing all files and subdirectories.
    """
    try:
        abs_path = os.path.abspath(directory_path)
        entries = os.listdir(abs_path)

        if not entries:
            return f"📂 Directory `{abs_path}` is empty."

        items = []
        for entry in sorted(entries):
            full_path = os.path.join(abs_path, entry)
            if os.path.isdir(full_path):
                items.append(f"  📁 {entry}/")
            else:
                size = os.path.getsize(full_path)
                items.append(f"  📄 {entry}  ({format_size(size)})")

        header = f"📂 Contents of `{abs_path}` ({len(entries)} items):\n"
        return header + "\n".join(items)
    except FileNotFoundError:
        return f"❌ Error: Directory not found — `{directory_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{directory_path}`"
    except Exception as e:
        return f"❌ Error listing directory `{directory_path}`: {e}"
