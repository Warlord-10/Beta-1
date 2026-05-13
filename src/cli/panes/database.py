"""Database pane — live view of the scheduler.sqlite database.

Shows the two tables we own: `tasks` (scheduler) and `llm_cost` (cost ledger).
Auto-refreshes every 2 seconds; pausable via the toolbar.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, DataTable, Static


_TASK_COLS = (
    "task_id",
    "task_description",
    "schedule_type",
    "is_enabled",
    "next_run_at",
    "last_run_at",
)
_COST_COLS = (
    "id",
    "registry_key",
    "model_name",
    "provider",
    "input_tokens",
    "output_tokens",
    "estimated_cost",
    "created_at",
)


class DatabasePane(Container):
    """Read-only view of the SQLite tables, auto-refreshed."""

    REFRESH_SECS = 2.0

    DEFAULT_CSS = """
    DatabasePane { padding: 1 2; }
    DatabasePane .section { padding: 1 0 0 0; color: $accent; }
    DatabasePane #db-controls { height: auto; padding: 0 0 1 0; }
    DatabasePane #db-status   { padding: 0 0 1 0; color: $text-muted; }
    DatabasePane DataTable { height: 12; }
    DatabasePane Button { margin-right: 1; }
    """

    # <repo>/data/scheduler.sqlite — kept in lockstep with src/cost/store.py
    # but computed locally so this pane can be imported before the cost stack
    # (avoids an init-time circular import via src.cost → src.llms).
    _DB_PATH = Path(__file__).resolve().parents[3] / "data" / "scheduler.sqlite"

    def __init__(self) -> None:
        super().__init__()
        self._db_path = self._DB_PATH
        self._auto = True
        # Track which columns each table currently shows so we don't blow away
        # the schema unnecessarily on each refresh.
        self._task_cols: tuple[str, ...] = ()
        self._cost_cols: tuple[str, ...] = ()

    # ── layout ───────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(
            f"🗄️  [bold]Database[/]   [dim]{self._db_path}[/]", markup=True
        )
        with Horizontal(id="db-controls"):
            yield Button("Refresh", id="db-refresh", variant="primary")
            yield Button("Pause auto-refresh", id="db-pause")
        yield Static("", id="db-status", markup=True)

        yield Static("[b]tasks[/]", classes="section", markup=True)
        yield DataTable(id="db-tasks", zebra_stripes=True)

        yield Static(
            "[b]llm_cost[/]  (most recent 50)", classes="section", markup=True
        )
        yield DataTable(id="db-cost", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(self.REFRESH_SECS, self._tick)

    # ── interaction ──────────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "db-refresh":
            self.refresh_data()
        elif event.button.id == "db-pause":
            self._auto = not self._auto
            event.button.label = (
                "Resume auto-refresh" if not self._auto else "Pause auto-refresh"
            )

    def _tick(self) -> None:
        if self._auto:
            self.refresh_data()

    # ── refresh ──────────────────────────────────────────────────────────
    def refresh_data(self) -> None:
        if not self._db_path.exists():
            self._set_status(f"[red]DB not found:[/] {self._db_path}")
            return

        self._task_cols = self._render_query(
            "db-tasks",
            "SELECT * FROM tasks ORDER BY rowid DESC",
            preferred=_TASK_COLS,
            previous=self._task_cols,
        )
        self._cost_cols = self._render_query(
            "db-cost",
            "SELECT * FROM llm_cost ORDER BY id DESC LIMIT 50",
            preferred=_COST_COLS,
            previous=self._cost_cols,
        )

        now = datetime.now().strftime("%H:%M:%S")
        auto = "auto: on" if self._auto else "auto: off"
        self._set_status(
            f"[dim]last refresh {now} · {auto} · every {int(self.REFRESH_SECS)}s[/]"
        )

    # ── query → DataTable ────────────────────────────────────────────────
    def _render_query(
        self,
        table_id: str,
        sql: str,
        *,
        preferred: Iterable[str],
        previous: tuple[str, ...],
    ) -> tuple[str, ...]:
        try:
            cols, rows = self._query(sql)
        except sqlite3.OperationalError:
            cols, rows = [], []

        table = self.query_one(f"#{table_id}", DataTable)
        if not cols:
            if previous:
                table.clear(columns=True)
            return ()

        display = [c for c in preferred if c in cols] or cols
        idxs = [cols.index(c) for c in display]

        if tuple(display) != previous:
            table.clear(columns=True)
            table.add_columns(*display)
        table.clear()
        for r in rows:
            table.add_row(*[self._cell(r[i]) for i in idxs])
        return tuple(display)

    def _query(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        finally:
            conn.close()
        return cols, rows

    @staticmethod
    def _cell(v) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.4f}"
        s = str(v)
        return s if len(s) <= 80 else s[:77] + "…"

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#db-status", Static).update(text)
        except Exception:
            pass
