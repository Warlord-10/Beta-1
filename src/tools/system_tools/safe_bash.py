"""Tool: safe_bash — Execute read-only / non-destructive shell commands.

Designed for the Chat Agent which should be able to inspect the system
environment but NOT modify it. Destructive commands (rm, sudo, mv, etc.)
are blocked at the tool level, regardless of what the LLM requests.
"""

import re
import subprocess

from langchain_core.tools import tool

# ── Allowed command prefixes (read/list/info only) ──────────────────
_ALLOWED_PREFIXES = (
    "ls", "cat", "head", "tail", "wc", "file", "which", "where",
    "whoami", "hostname", "uname", "date", "uptime", "df", "du",
    "echo", "env", "printenv", "pwd",
    "python --version", "python3 --version", "pip --version",
    "pip3 --version", "pip list", "pip3 list", "pip show", "pip3 show",
    "node --version", "npm --version", "npm list",
    "git status", "git log", "git branch", "git diff", "git show",
    "git remote", "git tag",
    "find", "grep", "rg", "tree",
)

# ── Explicitly blocked patterns (safety net) ────────────────────────
_BLOCKED_PATTERNS = [
    r"\brm\b",       r"\bsudo\b",      r"\bchmod\b",     r"\bchown\b",
    r"\bmkfs\b",     r"\bdd\b",        r"\bkill\b",      r"\bpkill\b",
    r"\breboot\b",   r"\bshutdown\b",  r"\bmv\b",        r"\bcp\b",
    r"\bmkdir\b",    r"\brmdir\b",     r"\btouch\b",     r"\bln\b",
    r"\bcurl\b.*-[dDXoPT]",            # curl with write flags
    r"\bwget\b",     r"\bnpm\s+install", r"\bpip\s+install",
    r"\bapt\b",      r"\bbrew\b",      r"\byum\b",       r"\bdnf\b",
    r">",            r"\btee\b",       # output redirection / tee
]


def _is_command_safe(command: str) -> bool:
    """Return True only if the command starts with an allowed prefix
    AND does not match any blocked pattern."""
    stripped = command.strip()

    # Must start with an allowed prefix
    starts_ok = any(
        stripped.startswith(prefix) for prefix in _ALLOWED_PREFIXES
    )
    if not starts_ok:
        return False

    # Must not match any blocked pattern
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, stripped):
            return False

    return True


@tool
def safe_bash(command: str, timeout: int = 30) -> str:
    """Execute a **read-only** shell command and return its output.

    Only non-destructive commands are allowed (ls, cat, grep, git status,
    python --version, etc.). Commands that modify the filesystem or
    system state are blocked for safety.

    Args:
        command: The shell command to execute.
        timeout: Max seconds to wait before killing the process. Defaults to 30.

    Returns:
        Combined stdout and stderr output, or a descriptive error.
    """
    if not _is_command_safe(command):
        return (
            f"🚫 Blocked: `{command}` is not in the allowed command list.\n"
            "Only read-only / inspection commands are permitted for the chat agent.\n"
            "If the user needs this command, delegate the task to the planner."
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += f"stdout:\n{result.stdout}\n"
        if result.stderr:
            output += f"stderr:\n{result.stderr}\n"
        if result.returncode != 0:
            output += f"⚠️ Exit code: {result.returncode}\n"
        return output.strip() or "✅ Command completed with no output."
    except subprocess.TimeoutExpired:
        return f"❌ Error: Command timed out after {timeout}s — `{command}`"
    except Exception as e:
        return f"❌ Error executing command: {e}"
