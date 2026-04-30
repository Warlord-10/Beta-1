"""Beta-1 — Central configuration / settings.

User-tunable values are loaded from `config/settings.json` at import time
into a single mutable `SETTINGS` object. The TUI (or any other frontend)
can mutate attributes at runtime and call `SETTINGS.save()` to persist.

Override the file location with `BETA1_SETTINGS_FILE`.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS_FILE = _REPO_ROOT / "config" / "settings.json"

# Keys injected at runtime — never persisted back to settings.json.
_RUNTIME_KEYS = {"LOG_FILE_PATH", "DEFAULT_CWD"}


def _settings_path() -> Path:
    return Path(os.environ.get("BETA1_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE))


def _load_settings_file() -> dict:
    path = _settings_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Settings file not found: {path}. "
            f"Set BETA1_SETTINGS_FILE or create the file."
        )
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid settings file {path}: expected JSON object.")
    return data


class Settings:
    """Mutable settings container. Attributes mirror keys in settings.json."""

    def __init__(self, data: dict) -> None:
        for k, v in data.items():
            setattr(self, k, v)

    def keys(self) -> list[str]:
        return [k for k in self.__dict__.keys() if not k.startswith("_")]

    def persistent_keys(self) -> list[str]:
        return [k for k in self.keys() if k not in _RUNTIME_KEYS]

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.persistent_keys()}

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def save(self) -> Path:
        """Persist current values back to settings.json (excluding runtime keys)."""
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path


_data = _load_settings_file()
_data.update({
    "LOG_FILE_PATH": os.path.join(_REPO_ROOT, "logs", f"{date.today()}.log"),
    "DEFAULT_CWD": os.getcwd(),
})

SETTINGS = Settings(_data)
