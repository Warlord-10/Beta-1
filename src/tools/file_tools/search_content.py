"""Tool: search_content — Search inside files for matching text (grep-like)."""

import os
import mimetypes
from typing import Optional

from langchain_core.tools import tool

# Directories to skip
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}

# Max file size to search (skip large/binary files) — 1 MB
_MAX_FILE_SIZE = 1_048_576


@tool
def search_content(
    directory: str,
    query: str,
    max_results: int = 20,
    file_extension: Optional[str] = None,
    case_sensitive: bool = False,
) -> str:
    """Search inside files for lines containing the given text (like grep).

    Performs fast line-by-line substring matching. Skips binary files and
    very large files automatically for performance.

    Args:
        directory: The root directory to search in.
        query: The text to search for inside files.
        max_results: Maximum number of matching lines to return (default 20).
        file_extension: Optional — only search files with this extension
                        (without the dot, e.g. "py", "txt").
        case_sensitive: Whether the search is case-sensitive (default False).

    Returns:
        A formatted string listing matching lines with file paths and line numbers.
    """
    try:
        abs_dir = os.path.abspath(directory)
        if not os.path.isdir(abs_dir):
            return f"❌ Error: Directory not found — `{directory}`"

        search_query = query if case_sensitive else query.lower()
        matches: list[str] = []
        files_searched = 0

        for root, dirs, files in os.walk(abs_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            for filename in files:
                # Extension filter
                if file_extension and not filename.endswith(f".{file_extension}"):
                    continue

                filepath = os.path.join(root, filename)

                # Skip binary files by MIME type
                mime, _ = mimetypes.guess_type(filepath)
                if mime and not mime.startswith("text") and mime != "application/json":
                    continue

                # Skip very large files
                try:
                    if os.path.getsize(filepath) > _MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                # Search line by line
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        files_searched += 1
                        for line_num, line in enumerate(f, start=1):
                            compare_line = line if case_sensitive else line.lower()
                            if search_query in compare_line:
                                rel_path = os.path.relpath(filepath, abs_dir)
                                snippet = line.strip()
                                if len(snippet) > 120:
                                    snippet = snippet[:120] + "…"
                                matches.append(f"  📄 {rel_path}:{line_num}  →  {snippet}")

                                if len(matches) >= max_results:
                                    break
                except (PermissionError, OSError):
                    continue

                if len(matches) >= max_results:
                    break

            if len(matches) >= max_results:
                break

        if not matches:
            suffix = f" (extension: .{file_extension})" if file_extension else ""
            return (
                f"🔍 No content matches for `{query}` in `{abs_dir}`{suffix}.\n"
                f"   Searched {files_searched} file(s)."
            )

        header = (
            f"🔍 Found {len(matches)} match(es) for `{query}` "
            f"across {files_searched} file(s) in `{abs_dir}`:\n"
        )
        truncated = f"\n  ⚠️  (limited to {max_results} results)" if len(matches) >= max_results else ""
        return header + "\n".join(matches) + truncated

    except PermissionError:
        return f"❌ Error: Permission denied — `{directory}`"
    except Exception as e:
        return f"❌ Error searching content in `{directory}`: {e}"
