"""Schedules pane — lists APScheduler tasks from the scheduler store."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Static

from ._common import fmt_iso, fmt_schedule


class SchedulesPane(Container):
    DEFAULT_CSS = """
    SchedulesPane { padding: 1 2; }
    SchedulesPane DataTable { height: 1fr; }
    SchedulesPane #schedules-empty { padding: 1 0; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📅  [bold]Schedules[/]", markup=True)
        yield Static("", id="schedules-empty", markup=True)
        yield DataTable(id="schedules-table", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns(
            "Next run", "Description", "Type", "Schedule", "Status", "Last run"
        )
        self.refresh_data()

    def refresh_data(self) -> None:
        tasks = self._load_tasks()
        t = self.query_one(DataTable)
        t.clear()
        empty = self.query_one("#schedules-empty", Static)
        if not tasks:
            empty.update("[dim]No scheduled tasks yet.[/]")
            return
        empty.update("")
        for task in tasks:
            status = "✅ Active" if task.is_enabled else "⏸ Paused"
            t.add_row(
                fmt_iso(task.next_run_at),
                task.task_description or "—",
                task.schedule_type,
                fmt_schedule(task.schedule_type, task.schedule_params),
                status,
                fmt_iso(task.last_run_at),
            )

    @staticmethod
    def _load_tasks():
        try:
            from src.scheduler.scheduler_manager import SchedulerManager

            return SchedulerManager().store.list_all()
        except Exception:
            return []
