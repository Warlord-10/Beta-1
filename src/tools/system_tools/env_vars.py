"""Tool: env_vars — Read or set environment variables."""

import os

from langchain_core.tools import tool


@tool
def env_vars(action: str, name: str, value: str = "") -> str:
    """Read or set an environment variable.

    Args:
        action: "get" to read, "set" to set, "list" to list all.
        name: Name of the environment variable (ignored for "list").
        value: Value to set (only used when action is "set").

    Returns:
        The variable value, confirmation, or a listing.
    """
    if action == "get":
        val = os.environ.get(name)
        if val is None:
            return f"⚠️ Environment variable `{name}` is not set."
        return f"🔑 {name}={val}"
    elif action == "set":
        os.environ[name] = value
        return f"✅ Set `{name}={value}`"
    elif action == "list":
        items = sorted(os.environ.items())
        lines = [f"  {k}={v[:80]}{'…' if len(v) > 80 else ''}" for k, v in items]
        return f"🔑 Environment variables ({len(items)}):\n" + "\n".join(lines)
    else:
        return f"❌ Unknown action `{action}`. Use 'get', 'set', or 'list'."
