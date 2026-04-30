"""LLM cost — SQLite persistence layer.

Persists one row per LLM call in the same `data/scheduler.sqlite` DB
already used by the scheduler. Thread-safe via RLock since the
LangChain callback may fire from background workers.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from src.config.logger import get_logger

logger = get_logger("cost.store")

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "scheduler.sqlite")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS llm_cost (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    registry_key    TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    provider        TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cached_tokens   INTEGER NOT NULL DEFAULT 0,
    estimated_cost  REAL NOT NULL DEFAULT 0.0,
    task_id         TEXT,
    created_at      TEXT NOT NULL
);
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_llm_cost_created_at ON llm_cost(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_llm_cost_registry  ON llm_cost(registry_key);",
]


class CostStore:
    """SQLite-backed per-call cost ledger."""

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._ensure_db()

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(_CREATE_TABLE_SQL)
                for stmt in _INDEX_SQL:
                    conn.execute(stmt)
                conn.commit()
            finally:
                conn.close()
        logger.info("Cost store ready: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record(
        self,
        registry_key: str,
        model_name: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        estimated_cost: float = 0.0,
        task_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO llm_cost
                       (registry_key, model_name, provider,
                        input_tokens, output_tokens, cached_tokens,
                        estimated_cost, task_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        registry_key, model_name, provider,
                        input_tokens, output_tokens, cached_tokens,
                        estimated_cost, task_id, self._now(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def summary(self, since: Optional[datetime] = None) -> list[dict]:
        """Aggregate per registry_key. Optionally filter by `since` (UTC)."""
        sql = """SELECT registry_key, model_name, provider,
                        SUM(input_tokens)   AS input_tokens,
                        SUM(output_tokens)  AS output_tokens,
                        SUM(cached_tokens)  AS cached_tokens,
                        SUM(estimated_cost) AS estimated_cost,
                        COUNT(*)            AS call_count
                 FROM llm_cost"""
        params: tuple = ()
        if since is not None:
            sql += " WHERE created_at >= ?"
            params = (since.astimezone(timezone.utc).isoformat(),)
        sql += " GROUP BY registry_key, model_name, provider ORDER BY estimated_cost DESC"

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def total_cost(self, since: Optional[datetime] = None) -> float:
        sql = "SELECT COALESCE(SUM(estimated_cost), 0.0) AS total FROM llm_cost"
        params: tuple = ()
        if since is not None:
            sql += " WHERE created_at >= ?"
            params = (since.astimezone(timezone.utc).isoformat(),)

        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, params).fetchone()
            finally:
                conn.close()
        return float(row["total"]) if row else 0.0

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM llm_cost ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]


cost_store = CostStore()
