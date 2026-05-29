"""Settings pane — split into runtime-mutable vs restart-required values."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Static, Switch


# Top-level keys that take effect immediately when saved.
MUTABLE_KEYS: frozenset[str] = frozenset({
    "NAME",
    "daily_budget_usd",
    "is_planning_review",
    "planning_review_timeout_s",
})

# Top-level keys that require a process restart to take effect.
IMMUTABLE_KEYS: frozenset[str] = frozenset({
    "LOG_MODE",
    "MODELS_DIR",
    "TTS_PROVIDER",
})


def _wid(*parts: str) -> str:
    return "set--" + "--".join(p.replace("_", "-").replace(".", "-") for p in parts)


class SettingsPane(VerticalScroll):
    """Editor for SETTINGS, persisted to config/settings.json on Save."""

    DEFAULT_CSS = """
    SettingsPane { padding: 1 2; }
    SettingsPane .row { height: auto; width: 100%; margin-bottom: 1; }
    SettingsPane Label.label {
        width: 32;
        content-align: left middle;
        padding: 1 1 0 0;
    }
    SettingsPane Input  { width: 1fr; }
    SettingsPane Switch { width: 8; }
    SettingsPane .section { padding: 1 0 0 0; color: $accent; }
    SettingsPane .locked-value {
        width: 1fr;
        color: $text-muted;
        padding: 1 1 0 1;
        background: $panel;
    }
    SettingsPane #settings-status  { padding: 1 0 0 0; color: $text-muted; }
    SettingsPane #settings-actions { height: auto; padding: 1 0 0 0; }
    SettingsPane Button { margin-right: 2; }
    """

    # ── layout ───────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        from src.config.settings import SETTINGS

        yield Static(
            "⚙️  [bold]Settings[/]   [dim]config/settings.json[/]", markup=True
        )

        yield Static(
            "\n[b]Runtime — editable[/]   "
            "[dim]Takes effect immediately on Save[/]",
            classes="section", markup=True,
        )
        for key, value in self._top_level_scalars(SETTINGS, MUTABLE_KEYS):
            yield from self._row(key, value, editable=True)

        yield Static(
            "\n[b]Restart required[/]   "
            "[dim]🔒 Read-only — edit config/settings.json and restart[/]",
            classes="section", markup=True,
        )
        for key, value in self._top_level_scalars(SETTINGS, IMMUTABLE_KEYS):
            yield from self._row(key, value, editable=False)

        tts_cfg = getattr(SETTINGS, "TTS_CONFIG", None)
        if isinstance(tts_cfg, dict):
            yield Static(
                "\n[b]TTS_CONFIG[/]   [dim]🔒 Read-only — restart required[/]",
                classes="section", markup=True,
            )
            for provider, params in tts_cfg.items():
                yield Static(f"  [b]{provider}[/]", classes="section", markup=True)
                if not isinstance(params, dict):
                    continue
                for sub_key, sub_val in params.items():
                    yield from self._row(
                        sub_key, sub_val, editable=False,
                        label=f"    {sub_key}",
                    )

        leftover = list(self._top_level_scalars(
            SETTINGS, exclude=MUTABLE_KEYS | IMMUTABLE_KEYS,
        ))
        if leftover:
            yield Static(
                "\n[b]Other[/]   [dim]🔒 Read-only[/]",
                classes="section", markup=True,
            )
            for key, value in leftover:
                yield from self._row(key, value, editable=False)

        with Horizontal(id="settings-actions"):
            yield Button("Save", id="settings-save", variant="primary")
            yield Button("Reload", id="settings-reload")
        yield Static("", id="settings-status", markup=True)

    @staticmethod
    def _top_level_scalars(SETTINGS, include=None, exclude=None):
        for key in SETTINGS.persistent_keys():
            if include is not None and key not in include:
                continue
            if exclude is not None and key in exclude:
                continue
            value = getattr(SETTINGS, key)
            if isinstance(value, dict):
                continue
            yield key, value

    def _row(self, key: str, value, *, editable: bool, label: str | None = None):
        display = label if label is not None else key
        if not editable:
            display = f"🔒 {display}"

        with Horizontal(classes="row"):
            yield Label(f"{display}:", classes="label")
            if editable:
                if isinstance(value, bool):
                    yield Switch(value=value, id=_wid(key))
                else:
                    yield Input(value=str(value), id=_wid(key))
            else:
                yield Static(str(value), classes="locked-value")

    # ── persistence ──────────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            self._save()
        elif event.button.id == "settings-reload":
            self._reload()

    def _save(self) -> None:
        from src.config.settings import SETTINGS

        for key in SETTINGS.persistent_keys():
            if key not in MUTABLE_KEYS:
                continue
            cur = getattr(SETTINGS, key)
            if isinstance(cur, dict):
                continue
            setattr(SETTINGS, key, self._read(_wid(key), cur))

        try:
            path = SETTINGS.save()
            self._status(f"[green]✓ Saved to {path}[/]")
        except Exception as e:
            self._status(f"[red]✗ Save failed: {e}[/]")

    def _reload(self) -> None:
        from src.config.settings import SETTINGS

        for key in SETTINGS.persistent_keys():
            if key not in MUTABLE_KEYS:
                continue
            cur = getattr(SETTINGS, key)
            if isinstance(cur, dict):
                continue
            self._push(_wid(key), cur)
        self._status("[dim]Reloaded from in-memory settings.[/]")

    # ── widget I/O helpers ───────────────────────────────────────────────
    def _read(self, widget_id: str, original):
        try:
            if isinstance(original, bool):
                return bool(self.query_one(f"#{widget_id}", Switch).value)
            raw = self.query_one(f"#{widget_id}", Input).value
            return self._coerce(original, raw)
        except Exception:
            return original

    def _push(self, widget_id: str, value) -> None:
        try:
            if isinstance(value, bool):
                self.query_one(f"#{widget_id}", Switch).value = bool(value)
            else:
                self.query_one(f"#{widget_id}", Input).value = str(value)
        except Exception:
            pass

    @staticmethod
    def _coerce(original, raw: str):
        if isinstance(original, bool):
            return raw
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

    def _status(self, text: str) -> None:
        try:
            self.query_one("#settings-status", Static).update(text)
        except Exception:
            pass
