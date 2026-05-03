from datetime import datetime, timedelta, timezone
import json

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Switch,
)


def _is_bool_string(v) -> bool:
    return isinstance(v, str) and v.lower() in ("true", "false")


def _row_id(*parts: str) -> str:
    """Build a safe widget id from arbitrary key parts."""
    return "set--" + "--".join(p.replace("_", "-").replace(".", "-") for p in parts)


class SettingsPane(VerticalScroll):
    """Live editor for SETTINGS, persisted to config/settings.json on Save."""

    DEFAULT_CSS = """
    SettingsPane { padding: 1 2; }
    SettingsPane .row { height: auto; width: 100%; margin-bottom: 1; }
    SettingsPane Label.label {
        width: 32;
        content-align: left middle;
        padding: 1 1 0 0;
    }
    SettingsPane Input { width: 1fr; }
    SettingsPane Switch { width: 8; }
    SettingsPane .section {
        padding: 1 0 0 0;
        color: $accent;
    }
    SettingsPane #settings-status { padding: 1 0 0 0; color: $text-muted; }
    SettingsPane #settings-actions { height: auto; padding: 1 0 0 0; }
    SettingsPane Button { margin-right: 2; }
    """

    def compose(self) -> ComposeResult:
        from src.config.settings import SETTINGS

        yield Static("⚙️  [bold]Settings[/]  [dim]config/settings.json[/]", markup=True)

        # Top-level scalars (everything except dicts/lists).
        for key in SETTINGS.persistent_keys():
            value = getattr(SETTINGS, key)
            if isinstance(value, dict):
                continue  # rendered separately
            yield from self._scalar_row(key, value)

        # Nested TTS_CONFIG: render each provider's keys as a sub-section.
        tts_cfg = getattr(SETTINGS, "TTS_CONFIG", None)
        if isinstance(tts_cfg, dict):
            yield Static("\n[b]TTS_CONFIG[/]", classes="section", markup=True)
            for provider, params in tts_cfg.items():
                yield Static(f"  [b]{provider}[/]", classes="section", markup=True)
                if not isinstance(params, dict):
                    continue
                for sub_key, sub_val in params.items():
                    yield from self._scalar_row(
                        sub_key,
                        sub_val,
                        widget_id=_row_id("TTS_CONFIG", provider, sub_key),
                        label=f"    {sub_key}",
                    )

        with Horizontal(id="settings-actions"):
            yield Button("Save", id="settings-save", variant="primary")
            yield Button("Reload", id="settings-reload")
        yield Static("", id="settings-status", markup=True)

    # ── row helpers ──────────────────────────────────────────────────────
    def _scalar_row(
        self,
        key: str,
        value,
        widget_id: str | None = None,
        label: str | None = None,
    ):
        widget_id = widget_id or _row_id(key)
        with_label = label if label is not None else key
        with Horizontal(classes="row"):
            yield Label(f"{with_label}:", classes="label")
            if _is_bool_string(value):
                yield Switch(value=(value.lower() == "true"), id=widget_id)
            elif isinstance(value, bool):
                yield Switch(value=value, id=widget_id)
            else:
                yield Input(value=str(value), id=widget_id)

    # ── persistence ──────────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            self._save()
        elif event.button.id == "settings-reload":
            self._reload()

    def _coerce(self, original, raw: str):
        """Coerce input string back to the original value's type."""
        if isinstance(original, bool):
            return raw  # handled via Switch
        if isinstance(original, int) and not isinstance(original, bool):
            try:
                return int(raw)
            except ValueError:
                return original
        if isinstance(original, float):
            try:
                return float(raw)
            except ValueError:
                return original
        return raw

    def _read_widget(self, widget_id: str, original):
        try:
            if _is_bool_string(original) or isinstance(original, bool):
                w = self.query_one(f"#{widget_id}", Switch)
                if _is_bool_string(original):
                    return "true" if w.value else "false"
                return bool(w.value)
            w = self.query_one(f"#{widget_id}", Input)
            return self._coerce(original, w.value)
        except Exception:
            return original

    def _save(self) -> None:
        from src.config.settings import SETTINGS

        for key in SETTINGS.persistent_keys():
            cur = getattr(SETTINGS, key)
            if isinstance(cur, dict):
                if key == "TTS_CONFIG":
                    new_cfg = {}
                    for provider, params in cur.items():
                        if not isinstance(params, dict):
                            new_cfg[provider] = params
                            continue
                        new_params = {}
                        for sub_key, sub_val in params.items():
                            new_params[sub_key] = self._read_widget(
                                _row_id("TTS_CONFIG", provider, sub_key), sub_val
                            )
                        new_cfg[provider] = new_params
                    setattr(SETTINGS, key, new_cfg)
                continue
            setattr(SETTINGS, key, self._read_widget(_row_id(key), cur))

        try:
            path = SETTINGS.save()
            self._set_status(f"[green]✓ Saved to {path}[/]")
        except Exception as e:
            self._set_status(f"[red]✗ Save failed: {e}[/]")

    def _reload(self) -> None:
        """Refresh widget values from current SETTINGS in-memory state."""
        from src.config.settings import SETTINGS

        def push(widget_id: str, value) -> None:
            try:
                if _is_bool_string(value) or isinstance(value, bool):
                    w = self.query_one(f"#{widget_id}", Switch)
                    w.value = (
                        value.lower() == "true" if _is_bool_string(value) else bool(value)
                    )
                else:
                    w = self.query_one(f"#{widget_id}", Input)
                    w.value = str(value)
            except Exception:
                pass

        for key in SETTINGS.persistent_keys():
            cur = getattr(SETTINGS, key)
            if isinstance(cur, dict):
                if key == "TTS_CONFIG":
                    for provider, params in cur.items():
                        if not isinstance(params, dict):
                            continue
                        for sub_key, sub_val in params.items():
                            push(_row_id("TTS_CONFIG", provider, sub_key), sub_val)
                continue
            push(_row_id(key), cur)
        self._set_status("[dim]Reloaded from in-memory settings.[/]")

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#settings-status", Static).update(text)
        except Exception:
            pass


def _fmt_iso(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def _fmt_schedule(schedule_type: str, params: dict) -> str:
    try:
        if schedule_type == "cron":
            return " ".join(f"{k}={v}" for k, v in params.items()) or "cron"
        if schedule_type == "interval":
            return ", ".join(f"{k}={v}" for k, v in params.items()) or "interval"
        if schedule_type == "once":
            return _fmt_iso(params.get("run_date"))
    except Exception:
        pass
    return json.dumps(params)


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
        t.add_columns("Next run", "Description", "Type", "Schedule", "Status", "Last run")
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from src.scheduler.scheduler_manager import SchedulerManager
            store = SchedulerManager().store
            tasks = store.list_all()
        except Exception:
            tasks = []

        t = self.query_one(DataTable)
        t.clear()
        empty_msg = self.query_one("#schedules-empty", Static)
        if not tasks:
            empty_msg.update("[dim]No scheduled tasks yet.[/]")
            return
        empty_msg.update("")
        for task in tasks:
            status = "✅ Active" if task.is_enabled else "⏸ Paused"
            t.add_row(
                _fmt_iso(task.next_run_at),
                task.task_description or "—",
                task.schedule_type,
                _fmt_schedule(task.schedule_type, task.schedule_params),
                status,
                _fmt_iso(task.last_run_at),
            )


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
        t.add_columns("Model", "Provider", "In", "Out", "Cached", "Calls", "Cost (USD)")
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from src.cost.store import cost_store
        except Exception:
            return

        now = datetime.now(timezone.utc)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_week = now - timedelta(days=7)

        today = cost_store.total_cost(since=start_today)
        week = cost_store.total_cost(since=start_week)
        all_time = cost_store.total_cost()
        rows = cost_store.summary()

        totals = self.query_one("#cost-totals", Static)
        totals.update(
            f"[b]Today[/] ${today:.4f}   "
            f"[b]Last 7d[/] ${week:.4f}   "
            f"[b]All time[/] ${all_time:.4f}"
        )

        t = self.query_one(DataTable)
        t.clear()
        for r in rows:
            t.add_row(
                r["registry_key"],
                r["provider"],
                f"{int(r['input_tokens']):,}",
                f"{int(r['output_tokens']):,}",
                f"{int(r['cached_tokens']):,}",
                str(int(r["call_count"])),
                f"${float(r['estimated_cost']):.4f}",
            )


class TasksPane(Container):
    DEFAULT_CSS = """
    TasksPane { padding: 2 3; }
    TasksPane Checkbox { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("✅  [bold]Tasks[/]\n", markup=True)
        yield Checkbox("Finish writing the Textual GUI demo", value=True)
        yield Checkbox("Review pull request #428", value=False)
        yield Checkbox("Call the dentist", value=False)
        yield Checkbox("Prepare slides for Friday's demo", value=False)
        yield Checkbox("Read chapter 4 of 'Designing ML Systems'", value=False)


class SessionsPane(Container):
    DEFAULT_CSS = """
    SessionsPane { padding: 2 3; }
    SessionsPane ListView { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("🗂️  [bold]Sessions[/]\n", markup=True)
        yield ListView(
            ListItem(
                Static("● [b]Planning Q3 roadmap[/]   [dim](2h ago · 42 messages)[/]")
            ),
            ListItem(
                Static(
                    "○ [b]Debug the payment service[/]   [dim](yesterday · 17 messages)[/]"
                )
            ),
            ListItem(
                Static(
                    "○ [b]Weekend trip brainstorm[/]   [dim](3 days ago · 8 messages)[/]"
                )
            ),
            ListItem(
                Static("○ [b]Resume review[/]   [dim](last week · 23 messages)[/]")
            ),
        )


class ContextsPane(Container):
    DEFAULT_CSS = """
    ContextsPane { padding: 2 3; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📚  [bold]Loaded Contexts[/]\n", markup=True)
        yield Static(
            "• [green]●[/] [b]project-spec.md[/]      [dim]1.2k tokens[/]\n"
            "• [green]●[/] [b]api-reference.pdf[/]    [dim]8.4k tokens[/]\n"
            "• [yellow]●[/] [b]meeting-notes.txt[/]   [dim]0.6k tokens[/]\n"
            "• [dim]○[/]  [b]old-design.md[/]          [dim]unloaded[/]\n\n"
            "[dim]Total active context: 10.2k / 200k tokens[/]",
            markup=True,
        )
