"""Shared formatters used by multiple panes."""

from __future__ import annotations

from datetime import datetime
import json


def fmt_iso(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def fmt_schedule(schedule_type: str, params: dict) -> str:
    try:
        if schedule_type == "cron":
            return " ".join(f"{k}={v}" for k, v in params.items()) or "cron"
        if schedule_type == "interval":
            return ", ".join(f"{k}={v}" for k, v in params.items()) or "interval"
        if schedule_type == "once":
            return fmt_iso(params.get("run_date"))
    except Exception:
        pass
    return json.dumps(params)
