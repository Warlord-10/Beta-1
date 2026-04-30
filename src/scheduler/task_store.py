"""Scheduler — SQLite persistence layer for TaskRecords.

Handles all CRUD operations against `data/scheduler.sqlite`.
Thread-safe: uses a threading lock for all DB operations since
APScheduler's background thread may write concurrently with the CLI.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from src.scheduler.models import TaskRecord
from src.config.logger import get_logger

logger = get_logger("scheduler.task_store")

# Database path (relative to project root)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "scheduler.sqlite")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id           TEXT PRIMARY KEY,
    task_description  TEXT NOT NULL DEFAULT '',
    schedule_type     TEXT NOT NULL DEFAULT 'cron',
    schedule_params   TEXT NOT NULL DEFAULT '{}',
    is_enabled        INTEGER NOT NULL DEFAULT 1,
    task_plan         TEXT NOT NULL DEFAULT '',
    last_task_result  TEXT NOT NULL DEFAULT '',
    last_run_at       TEXT,
    next_run_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
"""


class TaskStore:
    """SQLite-backed CRUD store for scheduled tasks.

    Thread-safe — all operations are protected by a reentrant lock.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._ensure_db()

    # ── Internal helpers ────────────────────────────────────────────

    def _ensure_db(self):
        """Create the data directory and tasks table if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(_CREATE_TABLE_SQL)
                conn.commit()
            finally:
                conn.close()
        logger.info("Task store ready: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── CRUD operations ─────────────────────────────────────────────

    def create(self, record: TaskRecord) -> TaskRecord:
        """Insert a new task. Returns the created record."""
        now = self._now()
        record.created_at = now
        record.updated_at = now
        data = record.to_dict()

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO tasks
                       (task_id, task_description, schedule_type, schedule_params,
                        is_enabled, task_plan, last_task_result, last_run_at,
                        next_run_at, created_at, updated_at)
                       VALUES
                       (:task_id, :task_description, :schedule_type, :schedule_params,
                        :is_enabled, :task_plan, :last_task_result, :last_run_at,
                        :next_run_at, :created_at, :updated_at)""",
                    data,
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("Created task %s: %s", record.task_id[:8], record.task_description)
        return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        """Fetch a single task by ID. Returns None if not found."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None
        return TaskRecord.from_row(row)

    def list_all(self) -> list[TaskRecord]:
        """Fetch all tasks, ordered by creation date."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC"
                ).fetchall()
            finally:
                conn.close()

        return [TaskRecord.from_row(r) for r in rows]

    def list_all_active(self) -> list[TaskRecord]:
        """Fetch all tasks, ordered by creation date."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE is_enabled = 1 ORDER BY created_at DESC"
                ).fetchall()
            finally:
                conn.close()

        return [TaskRecord.from_row(r) for r in rows]

    def update(self, task_id: str, **fields) -> Optional[TaskRecord]:
        """Partial update — only the provided fields are changed.

        Allowed fields: task_description, schedule_type, schedule_params,
        is_enabled, task_plan.

        Returns the updated record, or None if task_id not found.
        """
        allowed = {
            "task_description", "schedule_type", "schedule_params",
            "is_enabled", "task_plan",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(task_id)

        # Serialise schedule_params if provided
        if "schedule_params" in updates and isinstance(updates["schedule_params"], dict):
            import json
            updates["schedule_params"] = json.dumps(updates["schedule_params"])

        updates["updated_at"] = self._now()

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["task_id"] = task_id

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    f"UPDATE tasks SET {set_clause} WHERE task_id = :task_id",
                    updates,
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None
            finally:
                conn.close()

        logger.info("Updated task %s: %s", task_id[:8], list(fields.keys()))
        return self.get(task_id)

    def delete(self, task_id: str) -> bool:
        """Delete a task by ID. Returns True if a row was deleted."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM tasks WHERE task_id = ?", (task_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
            finally:
                conn.close()

        if deleted:
            logger.info("Deleted task %s", task_id[:8])
        return deleted

    def set_enabled(self, task_id: str, enabled: bool) -> Optional[TaskRecord]:
        """Toggle the is_enabled flag. Returns updated record or None."""
        return self.update(task_id, is_enabled=enabled)

    def update_last_result(
        self, task_id: str, result: str, run_at: Optional[str] = None
    ) -> None:
        """Update the last execution result and timestamp."""
        run_at = run_at or self._now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """UPDATE tasks
                       SET last_task_result = ?, last_run_at = ?, updated_at = ?
                       WHERE task_id = ?""",
                    (result, run_at, self._now(), task_id),
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("Updated last result for task %s", task_id[:8])

    def find_by_id_prefix(self, prefix: str) -> Optional[TaskRecord]:
        """Find a task whose ID starts with the given prefix.

        Useful for UX — users can type the first 8 chars of the UUID.
        Returns None if no match or multiple matches.
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE task_id LIKE ?", (f"{prefix}%",)
                ).fetchall()
            finally:
                conn.close()

        if len(rows) == 1:
            return TaskRecord.from_row(rows[0])
        return None
