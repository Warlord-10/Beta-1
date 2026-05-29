"""Costs pane — summary of LLM spend from the cost store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Static


class CostsPane(Container):
    DEFAULT_CSS = """
    CostsPane { padding: 1 2; }
    CostsPane DataTable { height: 1fr; }
    CostsPane #cost-totals { padding: 0 0 1 0; }
    """

    def compose(self) -> ComposeResult:
        yield Static("💰  [bold]LLM Cost[/]", markup=True)
        yield Static("", id="cost-totals", markup=True)
        yield DataTable(id="costs-table", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns(
            "Model", "Provider", "In", "Out", "Cached", "Calls", "Cost (USD)"
        )
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from src.cost.store import cost_store
        except Exception:
            return

        now = datetime.now(timezone.utc)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_week = now - timedelta(days=7)

        self.query_one("#cost-totals", Static).update(
            f"[b]Today[/] ${cost_store.total_cost(since=start_today):.4f}   "
            f"[b]Last 7d[/] ${cost_store.total_cost(since=start_week):.4f}   "
            f"[b]All time[/] ${cost_store.total_cost():.4f}"
        )

        t = self.query_one(DataTable)
        t.clear()
        for r in cost_store.summary():
            t.add_row(
                r["registry_key"],
                r["provider"],
                f"{int(r['input_tokens']):,}",
                f"{int(r['output_tokens']):,}",
                f"{int(r['cached_tokens']):,}",
                str(int(r["call_count"])),
                f"${float(r['estimated_cost']):.4f}",
            )
