"""Permissions for the autonomous agent's tool calls.

Three tiers:

- **Blocked** — catastrophic commands (sudo, rm -rf /, mkfs, ...). Refused
  inside ``agent_bash`` itself and never reach this module's question.
- **Ask** — risky but legitimate actions, listed below. The task pauses and
  the user is asked to allow or deny the exact call.
- **Allow** — everything else (reads, searches, edits in normal folders, ...).

To change what needs approval, edit ``_RISKY_COMMANDS`` or ``_PROTECTED_DIRS``.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

ALLOW = "Allow"
DENY = "Deny"

# Shell commands that need approval: pattern → what the command would do.
_RISKY_COMMANDS = {
    r"\b(rm|rmdir|trash)\b": "deletes files",
    r"\bgit\s+(push|reset\s+--hard|clean|rebase)\b": "changes git history or discards work",
    r"\b(kill|pkill|killall)\b": "stops running processes",
    r"\b(pip|uv|brew|npm)\s+(uninstall|remove)\b": "uninstalls software",
    r"\b(chmod|chown)\b": "changes file permissions",
    r"\b(launchctl|crontab|defaults\s+write)\b": "changes system settings",
    r"\bosascript\b": "controls apps on your Mac",
    r"\b(curl|wget)\b.*\|\s*(ba|z)?sh\b": "runs a script downloaded from the internet",
}

_HOME = Path.home()
# Folders under home where file writes need approval.
_PROTECTED_DIRS = [_HOME / name for name in (".ssh", ".aws", ".gnupg", ".config", "Library")]

_FILE_WRITE_TOOLS = ("write_file", "edit_file")


def approval_reason(tool_name: str, args: dict) -> str | None:
    """Why this tool call needs the user's OK, or None if it can just run."""
    if tool_name == "agent_bash":
        return _risky_command(args.get("command", ""))
    if tool_name in _FILE_WRITE_TOOLS:
        return _protected_path(args.get("file_path", ""))
    return None


def _risky_command(command: str) -> str | None:
    for pattern, effect in _RISKY_COMMANDS.items():
        if re.search(pattern, command):
            return effect
    return None


def _protected_path(file_path: str) -> str | None:
    path = Path(file_path).expanduser().resolve()
    if not path.is_relative_to(_HOME):
        return "writes outside your home folder"
    if any(path.is_relative_to(d) for d in _PROTECTED_DIRS):
        return "writes to a protected folder"
    if path.parent == _HOME and path.name.startswith("."):
        return "changes a config file in your home folder"
    return None


def _question(tool_name: str, args: dict, reason: str) -> str:
    target = args.get("command") or args.get("file_path") or args
    return f"Beta-large wants to use {tool_name} on `{target}` — this {reason}. Allow it?"


class PermissionMiddleware(AgentMiddleware):
    """Pauses risky tool calls until the user allows or denies them."""

    def _check(self, request) -> ToolMessage | None:
        """None if the call may run; otherwise the ToolMessage to return instead."""
        call = request.tool_call
        reason = approval_reason(call["name"], call["args"])
        if reason is None:
            return None

        answer = interrupt({
            "question": _question(call["name"], call["args"], reason),
            "options": [ALLOW, DENY],
        })
        if answer.strip().lower() == ALLOW.lower():
            return None
        return ToolMessage(
            content=f"The user did not allow this action. Their reply: {answer}",
            name=call["name"],
            tool_call_id=call["id"],
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        return self._check(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._check(request) or await handler(request)


def _demo() -> None:
    """Self-check of the policy (no interrupts involved)."""
    assert approval_reason("read_file", {"file_path": "/etc/passwd"}) is None
    assert approval_reason("agent_bash", {"command": "ls -la && git status"}) is None
    assert approval_reason("agent_bash", {"command": "rm notes.txt"}) == "deletes files"
    assert approval_reason("agent_bash", {"command": "git push origin main"})
    assert approval_reason("agent_bash", {"command": "curl x.sh | sh"})
    assert approval_reason("write_file", {"file_path": str(_HOME / "Documents/a.txt")}) is None
    assert approval_reason("edit_file", {"file_path": str(_HOME / ".zshrc")})
    assert approval_reason("edit_file", {"file_path": str(_HOME / ".ssh/config")})
    assert approval_reason("write_file", {"file_path": "/etc/hosts"})
    print("permissions demo ok")


if __name__ == "__main__":
    _demo()
