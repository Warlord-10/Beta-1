"""Tool: get_file_info — Retrieve metadata about a file or directory."""

import os
from datetime import datetime

from langchain_core.tools import tool

from src.tools.file_tools._helpers import format_size


@tool
def get_file_info(file_path: str) -> str:
    """Get metadata information about a file or directory.

    Args:
        file_path: The path of the file or directory to inspect.

    Returns:
        A formatted string with file metadata.
    """
    try:
        abs_path = os.path.abspath(file_path)
        stat = os.stat(abs_path)

        file_type = "Directory" if os.path.isdir(abs_path) else "File"
        size = format_size(stat.st_size)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        created = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        permissions = oct(stat.st_mode)[-3:]

        info = (
            f"ℹ️  Info for `{abs_path}`:\n"
            f"  • Type:        {file_type}\n"
            f"  • Size:        {size}\n"
            f"  • Modified:    {modified}\n"
            f"  • Created:     {created}\n"
            f"  • Permissions: {permissions}"
        )
        return info
    except FileNotFoundError:
        return f"❌ Error: Path not found — `{file_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error getting info for `{file_path}`: {e}"
