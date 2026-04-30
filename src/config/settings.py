"""Beta-1 — Central configuration / settings.

User-tunable values are loaded from `config/settings.json` at import time.
Top-level scalars can be overridden with environment variables of the same
name (e.g. `TTS_PROVIDER=kitten python main.py`).

Override the file location with the BETA1_SETTINGS_FILE env var.
"""

import json
import os
from dataclasses import dataclass, make_dataclass
from datetime import date
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS_FILE = _REPO_ROOT / "config" / "settings.json"


def _load_settings_file() -> dict:
    path = Path(os.environ.get("BETA1_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE))
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


_data = _load_settings_file()
_data.update({
    "LOG_FILE_PATH": os.path.join(
        _REPO_ROOT, "logs", f"{date.today()}.log"
    ),
    "DEFAULT_CWD": os.getcwd(),
})

Settings = make_dataclass("Settings",[(k, type(v)) for k, v in _data.items()])
SETTINGS = Settings(**_data)
