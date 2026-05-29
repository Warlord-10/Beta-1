"""Per-node error handling for LangGraph nodes.

The contract:
  - Every graph node is wrapped with :func:`node_guard` (or a thin alias).
  - On entry: log the node we're about to run.
  - On success: log the messages the node produced.
  - On failure: log the error with a traceback that's filtered down to our
    own source files (vendored LangChain frames are noise), then raise
    :class:`NodeFailure` so the runner can surface a clean
    ``<Agent:Node, ERROR: msg>`` string back to the chat agent.

``run_main_graph`` catches :class:`NodeFailure`, drops the session
checkpoint, and returns the formatted message — that's the entire policy.
"""

from __future__ import annotations

import functools
import os
import sys
import traceback
from typing import Callable

from src.config.logger import get_logger

try:
    from langgraph.errors import GraphBubbleUp as _ControlFlowSignal
except Exception:  # pragma: no cover
    class _ControlFlowSignal(Exception):  # type: ignore[no-redef]
        """Fallback if langgraph internals move."""


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class NodeFailure(Exception):
    """A graph node raised — capture which node and the underlying cause.

    The runner formats this as ``<agent:node, ERROR: msg>`` for the user.
    """

    def __init__(self, agent: str, node: str, cause: BaseException) -> None:
        self.agent = agent
        self.node = node
        self.cause = cause
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return f"<{self.agent}:{self.node}, ERROR: {self.cause}>"



def _is_app_frame(frame: traceback.FrameSummary) -> bool:
    """True for frames inside our project, excluding the venv / site-packages."""
    fn = frame.filename
    if not fn:
        return False
    abs_fn = os.path.abspath(fn)
    if "site-packages" in abs_fn or ".venv" in abs_fn:
        return False
    return abs_fn.startswith(_PROJECT_ROOT)


def format_app_traceback() -> str:
    """Return the current exception's traceback, keeping only our frames.

    Falls back to the full traceback when no frame in our codebase is on
    the stack (e.g. failure deep inside a vendored callback).
    """
    exc_type, exc, tb = sys.exc_info()
    if exc is None:
        return ""
    full = traceback.extract_tb(tb)
    app_only = [f for f in full if _is_app_frame(f)]
    frames = app_only or full
    lines = ["Traceback (most recent call last):\n"]
    lines.extend(traceback.format_list(frames))
    lines.append(f"{exc_type.__name__}: {exc}\n")
    return "".join(lines)


def _truncate(text: str, limit: int = 400) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _log_messages(logger, agent: str, node: str, result) -> None:
    """Log every AIMessage / SystemMessage produced by the node."""
    if not isinstance(result, dict):
        return
    messages = result.get("messages")
    if not messages:
        return
    for msg in messages:
        content = getattr(msg, "content", None)
        if not content:
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                logger.info(
                    "%s:%s tool_calls → %s",
                    agent, node,
                    _truncate(str(tool_calls)),
                )
            continue
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text") or p.get("thinking") or "")
                for p in content if isinstance(p, dict)
            )
        logger.info("%s:%s msg → %s", agent, node, _truncate(str(content)))


def node_guard(agent: str, node: str) -> Callable:
    """Wrap a node function so that:

    * entry / exit are logged,
    * its emitted messages are logged,
    * any exception is converted into :class:`NodeFailure` after logging
      a traceback trimmed to our own source files.
    """
    def decorator(fn):
        logger = get_logger(f"agents.{agent}")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            logger.info("→ %s:%s", agent, node)
            try:
                result = fn(*args, **kwargs)
            except NodeFailure:
                raise  # already wrapped further down the call stack
            except _ControlFlowSignal:
                # interrupt(), retry, … — let LangGraph see these.
                raise
            except Exception as exc:
                logger.error(
                    "✗ %s:%s failed — %s\n%s",
                    agent, node, exc,
                    format_app_traceback(),
                )
                raise NodeFailure(agent, node, exc) from exc
            _log_messages(logger, agent, node, result)
            logger.info("← %s:%s done", agent, node)
            return result

        return wrapper

    return decorator
