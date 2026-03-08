"""Tool: write_code — Write or update code in a file."""

import os

from langchain_core.tools import tool


@tool
def write_code(file_path: str, code: str, language: str = "python") -> str:
    """Write code content to a file, creating parent directories if needed.

    Args:
        file_path: Absolute or relative path to the file to write.
        code: The code content to write.
        language: Programming language (for logging/context). Defaults to "python".

    Returns:
        A confirmation message or error description.
    """
    try:
        abs_path = os.path.abspath(file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"✅ Wrote {language} code to `{abs_path}` ({len(code)} chars)"
    except PermissionError:
        return f"❌ Error: Permission denied — `{file_path}`"
    except Exception as e:
        return f"❌ Error writing code to `{file_path}`: {e}"
