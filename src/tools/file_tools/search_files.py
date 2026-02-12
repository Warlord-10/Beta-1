"""Tool: search_files — Find files and folders by name."""

import os
import fnmatch
from typing import Optional

from langchain_core.tools import tool

# Directories to skip for performance / relevance
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}


@tool
def search_files(
    directory: str,
    query: str,
    max_results: int = 20,
    file_extension: Optional[str] = None,
) -> str:
    """Search for files and folders by name within a directory (recursive).

    Uses fast case-insensitive substring matching by default.
    Supports glob patterns automatically when wildcards (* or ?) are detected
    (e.g. "*.py", "test_*").

    Args:
        directory: The root directory to search in.
        query: The search term — a plain substring (e.g. "config") or a glob
               pattern (e.g. "*.py", "report_202?").
        max_results: Maximum number of results to return (default 20).
        file_extension: Optional — filter results to only this extension
                        (without the dot, e.g. "py", "txt").

    Returns:
        A formatted string listing matching file/folder paths.
    """
    try:
        abs_dir = os.path.abspath(directory)
        if not os.path.isdir(abs_dir):
            return f"❌ Error: Directory not found — `{directory}`"

        # Detect if query is a glob pattern
        is_glob = "*" in query or "?" in query or "[" in query
        query_lower = query.lower()

        matches: list[str] = []

        for root, dirs, files in os.walk(abs_dir):
            # Prune noisy directories in-place (modifying dirs affects os.walk)
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]

            for name, is_dir in all_entries:
                # Apply extension filter (only for files)
                if file_extension and not is_dir:
                    if not name.endswith(f".{file_extension}"):
                        continue

                # Match logic
                if is_glob:
                    matched = fnmatch.fnmatch(name.lower(), query_lower)
                else:
                    matched = query_lower in name.lower()

                if matched:
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, abs_dir)
                    icon = "📁" if is_dir else "📄"
                    matches.append(f"  {icon} {rel_path}")

                    if len(matches) >= max_results:
                        break

            if len(matches) >= max_results:
                break

        if not matches:
            suffix = f" (extension: .{file_extension})" if file_extension else ""
            return f"🔍 No matches found for `{query}` in `{abs_dir}`{suffix}."

        header = f"🔍 Found {len(matches)} result(s) for `{query}` in `{abs_dir}`:\n"
        truncated = f"\n  ⚠️  (limited to {max_results} results)" if len(matches) >= max_results else ""
        return header + "\n".join(matches) + truncated

    except PermissionError:
        return f"❌ Error: Permission denied — `{directory}`"
    except Exception as e:
        return f"❌ Error searching `{directory}`: {e}"
