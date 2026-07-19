"""Shared environment context — the "where/when am I" block injected at the
start of every agent run.

Covers the ~90% of tasks that just need ambient awareness (cwd, date, time,
OS, user). Computed fresh on each call so the date/time is always current —
do NOT cache it.

Usage:
    from src.config.context import environment_context

    opening = f"{environment_context()}\n\nTask: {task}"
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime

from src.config.settings import SETTINGS


def environment_context() -> str:
    """Return a markdown block describing the current runtime environment."""
    now = datetime.now().astimezone()
    # ponytail: geographic location omitted — it needs an online geo/IP lookup
    # that's unreliable and rarely needed. Timezone is the honest proxy. Add a
    # real lookup only if a task genuinely depends on physical location.
    return "\n".join([
        "## Environment",
        f"- User: {getattr(SETTINGS, 'NAME', 'unknown')}",
        f"- Date & time: {now.strftime('%A %Y-%m-%d %H:%M:%S')} {now.tzname()}",
        f"- Working directory: {os.getcwd()}",
        f"- OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"- Python: {sys.version.split()[0]}",
    ])


if __name__ == "__main__":
    print(environment_context())
