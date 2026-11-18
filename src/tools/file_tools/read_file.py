"""Tool: read_file — Read the contents of a file."""

import os

from langchain_core.tools import tool


@tool
def read_file(file_path: str, offset: int = 1, limit: int = 2000) -> str:
    """Read a file with line numbers.

    Large files are read in parts: pass ``offset`` (1-based start line) and
    ``limit`` (number of lines) to page through them.

    Args:
        file_path: Absolute or relative path to the file to read.
        offset: Line number to start from (1-based).
        limit: Maximum number of lines to return.

    Returns:
        The requested lines, prefixed with their line numbers.
    """
    try:
        abs_path = os.path.abspath(file_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(offset, 1) - 1
        chunk = lines[start : start + limit]
        body = "".join(f"{start + i + 1:>6}\t{line}" for i, line in enumerate(chunk))
        footer = ""
        if start + limit < len(lines):
            footer = f"\n… {len(lines) - start - limit} more lines — read again with offset={start + limit + 1}"
        return f"📄 `{abs_path}` (lines {start + 1}-{start + len(chunk)} of {len(lines)}):\n\n{body}{footer}"
    except FileNotFoundError:
        return f"❌ Error: File not found — `{file_path}`"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error reading file `{file_path}`: {e}"
