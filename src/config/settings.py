"""Beta-1 — Central configuration / settings.

User-tunable values are loaded from `config/settings.json` at import time
into a single mutable `SETTINGS` object — read settings from it, never from
module-level copies. To change one, set the attribute and call
`SETTINGS.save()`, which rewrites the file.

Override the file location with `BETA1_SETTINGS_FILE`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS_FILE = _REPO_ROOT / "config" / "settings.json"

# Keys injected at runtime — never persisted back to settings.json.
_RUNTIME_KEYS = {"LOG_FILE_PATH"}


def _settings_path() -> Path:
    return Path(os.environ.get("BETA1_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE))


@dataclass
class Settings:
    LOG_MODE: str = "file"
    NAME: str = "DJ"

    LOG_FILE_PATH: str = os.path.join(_REPO_ROOT, "logs", f"{date.today()}.log")

    IS_GUI_ENABLED: bool = True

    OBSERVABILITY_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318"

    daily_budget_usd: float = 0

    # Chat agent context budget (tokens). The conversation is compacted once
    # its size crosses this.
    CHAT_CONTEXT_WINDOW: int = 16000

    MIC_SAMPLE_RATE: int = 48000

    STT_SAMPLE_RATE: int = 16000
    # DeepFilterNet noise suppression on the mic path. Off by default: it runs
    # on every mic block and slows TTS synthesis ~3x via CPU/GIL contention.
    IS_DEEPFILTERNET_ENABLED: bool = False
    # Every selectable STT model: name -> provider config. STT_CONFIG names
    # the one to load (picked in the TUI settings tab; applies on restart).
    STT_MODEL_LIST: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "parakeet-0.6b-v3": {"provider": "mlx", "model_name": "parakeet-tdt-0.6b-v3"},
        }
    )
    STT_CONFIG: str = "parakeet-0.6b-v3"

    # Same shape as STT. Each entry also names its output sample_rate, which
    # playback and the echo canceller run at (stripped before the provider).
    TTS_MODEL_LIST: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "kokoro-mlx": {
                "provider": "mlx", "model_name": "mlx-community/Kokoro-82M-bf16",
                "voice": "af_heart", "speed": 1.3, "lang_code": "a", "sample_rate": 24000,
            },
            "soprano-mlx": {
                "provider": "mlx", "model_name": "mlx-community/Soprano-1.1-80M-bf16",
                "temperature": 0.3, "sample_rate": 32000,
            },
            "pocket-tts-mlx": {
                "provider": "mlx", "model_name": "mlx-community/pocket-tts",
                "voice": "alba", "stream": True, "sample_rate": 24000,
            },
            "zonos3-mini-mlx": {
                "provider": "mlx", "model_name": "mlx-community/ZONOS3-Mini",
                "voice": "jett", "lang_code": "en", "stream": True, "sample_rate": 44100,
            },
            "kokoro": {
                "provider": "kokoro", "model_name": "hexgrad/Kokoro-82M",
                "voice_name": "af_heart", "speed": 1.3, "sample_rate": 24000,
            },
            "phonon": {
                "provider": "phonon", "model_name": "hf://gradium/phonon-31m-en",
                "voice_name": "Easton", "lang": "en", "quant": "q8", "sample_rate": 24000,
            },
            "supertonic": {
                "provider": "supertonic", "model_name": "supertonic-3",
                "voice_name": "F1", "speed": 1.05, "sample_rate": 44100,
            },
        }
    )
    TTS_CONFIG: str = "kokoro-mlx"

    @property
    def TTS_SAMPLE_RATE(self) -> int:
        # ponytail: read once at startup by TTS/AEC; picking another model in
        # the TUI changes this live, but nothing re-reads it until restart.
        return self.TTS_MODEL_LIST[self.TTS_CONFIG]["sample_rate"]

    def persistent_keys(self) -> list[str]:
        """Field names that represent real config — excludes runtime-injected
        keys (log path). Used by the settings pane to render/save rows."""
        return [f.name for f in fields(self) if f.name not in _RUNTIME_KEYS]

    def save(self) -> str:
        """Persist the config fields to the settings JSON file. Returns the path."""
        path = _settings_path()
        data = {k: getattr(self, k) for k in self.persistent_keys()}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return str(path)


def load_settings() -> Settings:
    """Defaults overlaid with `config/settings.json`. Keys missing from the
    file are written back so it always lists every setting."""
    settings = Settings()
    path = _settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e

    known = settings.persistent_keys()
    for key, value in data.items():
        if key in known:
            setattr(settings, key, value)
    if set(known) - set(data):
        settings.save()
    return settings


SETTINGS = load_settings()
