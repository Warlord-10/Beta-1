"""Tool: delete_file — Delete a file or directory."""

import os
import shutil

from langchain_core.tools import tool


@tool
def delete_file(file_path: str) -> str:
    """Delete a file or directory.

    Args:
        file_path: The path of the file or directory to delete.

    Returns:
        A confirmation message.
    """
    try:
        abs_path = os.path.abspath(file_path)

        if os.path.isdir(abs_path):
            shutil.rmtree(abs_path)
            return f"✅ Deleted directory: `{abs_path}`"
        elif os.path.isfile(abs_path):
            os.remove(abs_path)
            return f"✅ Deleted file: `{abs_path}`"
        else:
            return f"❌ Error: Path not found — `{file_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error deleting `{file_path}`: {e}"
