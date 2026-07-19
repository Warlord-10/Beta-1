"""Tool: agent_bash — write-capable terminal for the autonomous agent.

Unlike ``safe_bash`` (read-only, for the chat agent), this executes ANY
shell command — writes, installs, running scripts — and feeds stdout,
stderr, and the exit code back so the agent can see what happened and
decide its next step. This is the terminal-access loop that makes the
agent self-sustaining.

A small denylist blocks only *catastrophic, irreversible* commands
(wiping the disk, sudo, shutting the box down). It is a guardrail, NOT a
sandbox — the agent is trusted to operate inside the project.
"""

import re
import subprocess

from langchain_core.tools import tool

# Catastrophic / irreversible patterns — blocked regardless of the request.
# ponytail: guardrail, not a sandbox. Add patterns here if the agent finds a
# new way to hurt the host; don't try to enumerate every safe command.
_BLOCKED_PATTERNS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/(?:\s|$)",   # rm -rf / (root)
    r":\(\)\s*\{.*\|.*&.*\}",                  # fork bomb
    r"\bsudo\b", r"\bmkfs\b", r"\bdd\b",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r">\s*/dev/sd[a-z]", r"\bchmod\s+-R\s+777\s+/(?:\s|$)",
    r"git\s+push\s+.*--force", r"git\s+push\s+.*-f\b",
]


def _is_catastrophic(command: str) -> bool:
    return any(re.search(p, command) for p in _BLOCKED_PATTERNS)


@tool
def agent_bash(command: str, timeout: int = 60) -> str:
    """Run a shell command and return its combined output.

    Use this as your terminal: create/edit/move/delete files, install
    packages, run scripts and tests, use git, etc. The result includes
    stdout, stderr, and the exit code — read it to decide your next step.
    If a command fails, fix the cause and run it again.

    Args:
        command: The shell command to run. Chain with ``&&`` and change
            directory inline (``cd path && ...``) since each call starts
            in the repo root.
        timeout: Max seconds before the command is killed. Defaults to 60.

    Returns:
        stdout + stderr + exit code, or a descriptive error.
    """
    # ponytail: runs from repo root each call; use absolute paths or
    # `cd x && ...`. Add a persistent-cwd holder if the agent trips on this.
    if _is_catastrophic(command):
        return (
            f"🚫 Blocked: `{command}` looks catastrophic/irreversible and was "
            "not run. Rework the task without it."
        )

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {timeout}s — `{command}`"
    except Exception as e:  # noqa: BLE001 — surface anything to the agent
        return f"❌ Error executing command: {e}"

    parts = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    parts.append(f"exit code: {result.returncode}")
    return "\n".join(parts)


def _demo() -> None:
    """Self-check: success reports stdout+exit 0, denylist blocks rm -rf /."""
    ok = agent_bash.invoke({"command": "echo hello"})
    assert "hello" in ok and "exit code: 0" in ok, ok

    fail = agent_bash.invoke({"command": "ls /no/such/path/xyz"})
    assert "exit code: 0" not in fail, fail  # non-zero exit surfaced

    blocked = agent_bash.invoke({"command": "rm -rf /"})
    assert "Blocked" in blocked, blocked
    print("agent_bash demo ok")


if __name__ == "__main__":
    _demo()
