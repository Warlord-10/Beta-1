"""Shared, thread-safe view of the current autonomous-agent task.

One process-wide instance (``WORKFLOW_CONTEXT``) holds what the autonomous
agent is doing: the task, its live plan, the files it has changed, and status.

- The **autonomous agent** writes it (start/plan/files/finish) as it works, so
  its own plan stays in front of it and it doesn't lose the thread.
- The **chat agent** reads it via ``get_workflow_status`` and can stop it via
  ``cancel_workflow``.
- Every change is published to the **event bus** (``WorkflowStatus``) so the GUI
  can show live progress.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from langchain_core.tools import tool


@dataclass
class WorkflowContext:
    task: str = ""
    plan: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    status: str = "idle"  # idle | running | done | failed | cancelled
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # ── mutation (autonomous agent) ──────────────────────────────────
    def start(self, task: str) -> None:
        """Begin a new task — resets plan, files, and the cancel flag."""
        with self._lock:
            self.task = task
            self.plan = []
            self.files_changed = []
            self.status = "running"
            self._cancel.clear()
        self._publish()

    def set_plan(self, steps: list[str]) -> None:
        with self._lock:
            self.plan = list(steps)
        self._publish()

    def add_files(self, paths: list[str]) -> None:
        with self._lock:
            for p in paths:
                if p and p not in self.files_changed:
                    self.files_changed.append(p)
        self._publish()

    def finish(self, status: str = "done") -> None:
        with self._lock:
            self.status = status
        self._publish()

    # ── cancellation ─────────────────────────────────────────────────
    def request_cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    # ── read ─────────────────────────────────────────────────────────
    def render(self) -> str:
        with self._lock:
            if self.status == "idle":
                return "No autonomous task has run yet."
            plan = [f"  {s}" for s in self.plan] or ["  (no plan recorded yet)"]
            files = [f"  {f}" for f in self.files_changed] or ["  (none)"]
            return "\n".join([
                f"Task: {self.task or '(none)'}",
                f"Status: {self.status}",
                "",
                "Plan:",
                *plan,
                "",
                "Files changed:",
                *files,
            ])

    def _publish(self) -> None:
        """Fan a snapshot to the event bus so the GUI can react live."""
        from src.config.event_bus import EVENT_BUS, WorkflowStatus
        with self._lock:
            snap = WorkflowStatus(
                task=self.task,
                plan=list(self.plan),
                files_changed=list(self.files_changed),
                status=self.status,
            )
        EVENT_BUS.publish(snap)


# Process-wide singleton, mirroring global_queues / event_bus.
WORKFLOW_CONTEXT = WorkflowContext()


@tool
def get_workflow_status() -> str:
    """Show what the autonomous background agent is doing: its current task,
    plan checklist, status (idle/running/done/failed/cancelled), and the files
    it has created or changed. Call this to check progress or whether it has
    finished.
    """
    return WORKFLOW_CONTEXT.render()


@tool
def cancel_workflow() -> str:
    """Request cancellation of the running autonomous background task. It stops
    at its next step. Use when the user asks to stop/abort the running task.
    """
    if WORKFLOW_CONTEXT.status != "running":
        return "No background task is currently running."
    WORKFLOW_CONTEXT.request_cancel()
    return "Cancellation requested — the background task will stop shortly."


def _demo() -> None:
    """Self-check: start resets + clears cancel, files dedup, cancel flag."""
    ctx = WorkflowContext()
    assert "No autonomous task" in ctx.render()
    ctx.start("build a thing")
    ctx.set_plan(["[x] gather context", "[~] write code"])
    ctx.add_files(["a.py", "a.py", "b.py"])  # dup ignored
    out = ctx.render()
    assert "Status: running" in out and out.count("a.py") == 1, out
    ctx.request_cancel()
    assert ctx.is_cancelled()
    ctx.start("next")  # resets state AND cancel flag
    assert not ctx.is_cancelled() and ctx.files_changed == [], ctx
    print("workflow_context demo ok")


if __name__ == "__main__":
    _demo()
