"""Tool: copy_file — Copy a file or directory to a new location."""

import os
import shutil

from langchain_core.tools import tool


@tool
def copy_file(source_path: str, destination_path: str) -> str:
    """Copy a file or directory to a new location.

    Args:
        source_path: The path of the file or directory to copy.
        destination_path: The destination path for the copy.

    Returns:
        A confirmation message.
    """
    try:
        abs_source = os.path.abspath(source_path)
        abs_dest = os.path.abspath(destination_path)
        os.makedirs(os.path.dirname(abs_dest), exist_ok=True)

        if os.path.isdir(abs_source):
            shutil.copytree(abs_source, abs_dest)
        else:
            shutil.copy2(abs_source, abs_dest)

        return f"✅ Copied `{abs_source}` → `{abs_dest}`"
    except FileNotFoundError:
        return f"❌ Error: Source not found — `{source_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied."
    except Exception as e:
        return f"❌ Error copying `{source_path}`: {e}"
