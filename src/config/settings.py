"""Beta-1 — Central configuration / settings.

User-tunable values are loaded from `config/settings.json` at import time
into a single mutable `SETTINGS` object. The TUI (or any other frontend)
can mutate attributes at runtime and call `SETTINGS.save()` to persist.

Override the file location with `BETA1_SETTINGS_FILE`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS_FILE = _REPO_ROOT / "config" / "settings.json"

# Keys injected at runtime — never persisted back to settings.json.
_RUNTIME_KEYS = {"LOG_FILE_PATH", "DEFAULT_CWD"}


def _settings_path() -> Path:
    return Path(os.environ.get("BETA1_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE))


def load_settings_file() -> dict:
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


@dataclass
class Settings:
    LOG_MODE: str = "file"
    NAME: str = "DJ"
    MODELS_DIR: str = "models"

    LOG_FILE_PATH: str = os.path.join(_REPO_ROOT, "logs", f"{date.today()}.log")
    DEFAULT_CWD: str = os.getcwd()

    OBSERVABILITY_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318"

    daily_budget_usd: float = 0
    is_planning_review: bool = False

    planning_review_timeout_s: int = 120

    MIC_SAMPLE_RATE: int = 48000

    STT_SAMPLE_RATE: int = 16000
    STT_CONFIG: dict[str, Any] = field(
        default_factory=lambda: {
            "provider": "mlx",
            "model_name": "parakeet-tdt-0.6b-v3"
        }
    )
    
    TTS_SAMPLE_RATE: int = 24000
    TTS_CONFIG: dict[str, Any] = field(
        default_factory=lambda: {
            "provider": "kokoro",
            "voice_name": "af_heart",
            "speed": 1.3
        }
    )

    

SETTINGS = Settings()
print(SETTINGS)