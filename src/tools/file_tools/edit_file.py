"""Tool: edit_file — Replace an exact snippet inside an existing file."""

import os

from langchain_core.tools import tool


@tool
def edit_file(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit a file by replacing an exact snippet of text.

    Read the file first. ``old_string`` must match the file exactly (including
    indentation) and be unique unless ``replace_all`` is true — include a few
    surrounding lines to make it unique.

    Args:
        file_path: Path to the file to edit.
        old_string: Exact text to replace.
        new_string: Replacement text.
        replace_all: Replace every occurrence instead of exactly one.

    Returns:
        Confirmation, or an error explaining why nothing was changed.
    """
    try:
        abs_path = os.path.abspath(file_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"❌ Error: File not found — `{file_path}`"
    except Exception as e:
        return f"❌ Error reading file `{file_path}`: {e}"

    count = content.count(old_string)
    if not old_string or count == 0:
        return f"❌ Error: old_string not found in `{file_path}` — read the file and copy the text exactly."
    if count > 1 and not replace_all:
        return f"❌ Error: old_string occurs {count} times in `{file_path}` — add surrounding lines to make it unique, or set replace_all."

    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content.replace(old_string, new_string))
    except Exception as e:
        return f"❌ Error writing file `{file_path}`: {e}"
    return f"✅ Edited `{abs_path}` ({count if replace_all else 1} replacement(s))."
