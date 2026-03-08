"""Tool: git_ops — Perform common git operations."""

import subprocess

from langchain_core.tools import tool


@tool
def git_ops(operation: str, args: str = "", repo_path: str = ".") -> str:
    """Run a git operation in a repository.

    Args:
        operation: Git sub-command (e.g. "status", "log", "add", "commit", "diff", "branch").
        args: Additional arguments for the git command.
        repo_path: Path to the git repository. Defaults to current directory.

    Returns:
        Git command output or error description.
    """
    allowed_ops = {
        "status", "log", "diff", "branch", "add", "commit",
        "pull", "push", "checkout", "stash", "show", "remote",
    }
    if operation not in allowed_ops:
        return f"❌ Unsupported git operation: `{operation}`. Allowed: {', '.join(sorted(allowed_ops))}"

    cmd = f"git -C {repo_path} {operation} {args}".strip()
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        return output.strip() or f"✅ git {operation} completed with no output."
    except subprocess.TimeoutExpired:
        return f"❌ Error: git {operation} timed out."
    except Exception as e:
        return f"❌ Error running git {operation}: {e}"
