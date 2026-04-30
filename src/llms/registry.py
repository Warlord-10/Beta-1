
from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import make_dataclass


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS_FILE = _REPO_ROOT / "config" / "models.json"

with _DEFAULT_MODELS_FILE.open("r", encoding="utf-8") as f:
    _data = json.load(f)

Registry = make_dataclass("Registry", [(k, type(v)) for k, v in _data.items()])
MODEL_REGISTRY = Registry(**_data)