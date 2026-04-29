"""Scheduler — Data models.

Defines TaskRecord, the core data structure for a scheduled task.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import uuid
import json
import time

ID_EPOCH = 1777482000

@dataclass
class TaskRecord:
    """A single scheduled task persisted in SQLite.

    Fields:
        task_id:            Unique identifier (UUID).
        task_description:   What the agent should do when the task fires.
        schedule_type:      "cron" | "interval" | "once".
        schedule_params:    Dict of trigger parameters, e.g. {"hour": 9, "minute": 0}.
        is_enabled:         Whether the task is active (can be toggled without deleting).
        task_plan:          Optional detailed plan / step-by-step instructions.
        last_task_result:   Result string from the most recent execution.
        last_run_at:        ISO-8601 timestamp of last execution (or None).
        next_run_at:        ISO-8601 timestamp of next scheduled run (or None).
        created_at:         ISO-8601 timestamp of creation.
        updated_at:         ISO-8601 timestamp of last modification.
    """

    task_id: str = field(default_factory=lambda: str(int(time.time() - ID_EPOCH)))
    task_description: str = ""
    schedule_type: str = "cron"           # "cron" | "interval" | "once"
    schedule_params: dict = field(default_factory=dict)
    is_enabled: bool = True
    task_plan: str = ""
    last_task_result: str = ""
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


    def to_dict(self) -> dict:
        """Converts a TaskRecord object into a regular Python dictionary (schedule_params serialised as JSON string)."""
        d = asdict(self)
        d["schedule_params"] = json.dumps(d["schedule_params"])
        return d

    @classmethod
    def from_row(cls, row: dict) -> TaskRecord:
        """Creates a TaskRecord object from a database row."""
        data = dict(row)
        data["schedule_params"] = json.loads(data.get("schedule_params", "{}"))
        data["is_enabled"] = bool(data.get("is_enabled", 1))
        return cls(**data)

    def summary(self) -> str:
        """Human-readable one-liner for listing."""
        status = "✅ enabled" if self.is_enabled else "❌ disabled"
        last = self.last_run_at or "never"
        return (
            f"[{self.task_id[:8]}] {self.task_description!r} "
            f"({self.schedule_type} {json.dumps(self.schedule_params)}) "
            f"— {status} — last run: {last}"
        )
