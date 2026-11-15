"""Workflow entry point — runs a delegated task on the autonomous agent.

Invoked via :func:`run_main_graph` from the pipeline's workflow loop when the
chat agent delegates a request that needs multi-step work.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from src.config.logger import get_logger
from src.utils.errors import NodeFailure, format_app_traceback

logger = get_logger("workflow")


# Guarantees one autonomous task executes at a time across all callers.
_WORKFLOW_LOCK = threading.Lock()

# Sync interrupt handler — receives an interrupt payload and returns the
# user's answer. Kept for the upcoming ask_user route; nothing calls it yet.
InterruptHandler = Callable[[dict], str]


def run_main_graph(
    task_summary: str, on_interrupt: Optional[InterruptHandler] = None
) -> str:
    """Run a complex task via the autonomous agent."""
    from src.agents.autonomousagent.autonomous_agent import run_autonomous_agent

    logger.info("Starting workflow for task: %s", task_summary)
    # Serialise: only one autonomous task runs at a time. The single WorkflowLoop
    # already achieves this, but the lock also guards any direct/second caller
    # (e.g. a scheduled task) — the next caller blocks until this one finishes.
    try:
        with _WORKFLOW_LOCK:
            return run_autonomous_agent(task_summary)
    except NodeFailure as nf:
        logger.error("workflow halted: %s", nf.message)
        return nf.message
    except Exception as exc:
        logger.error(
            "workflow crashed — %s\n%s",
            exc,
            format_app_traceback(),
        )
        return f"<workflow:run_main_graph, ERROR: {exc}>"
