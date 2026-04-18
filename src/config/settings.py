"""Beta-1 — Central configuration / settings.

All tuneable knobs live here so you never have to hunt through code.
"""

import os
from datetime import datetime, timedelta, date
from dataclasses import dataclass
import json
from pathlib import Path

# Where agent & tool logs are written.
#   "terminal"  → print to stdout/stderr only
#   "file"      → write to LOG_FILE_PATH only
#   "both"      → write to both stdout and LOG_FILE_PATH
LOG_MODE: str = "file"

# Path to the log file (used when LOG_MODE is "file" or "both")
LOG_FILE_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
    f"{date.today()}.log",
)

DEFAULT_CWD: str = os.getcwd()

# The active TTS provider. Choose "supertonic", "kokoro", or "kitten"
TTS_PROVIDER: str = None

# Configuration for the Text-to-Speech engines
TTS_CONFIG = {
    "supertonic": {
        "voice_name": "F1",
        "sample_rate": 24000,
        "speed": 1.3,
        "total_steps": 30,
    },
    "kokoro": {
        "voice_name": "af_heart",
        "sample_rate": 24000,
        "speed": 1.3,
    },
    "kitten": {
        "model_name": "KittenML/kitten-tts-mini-0.8",
        "voice_name": "Jasper",
        "sample_rate": 24000,
        "speed": 1.3,
    }
}

@dataclass
class Settings:
    LOG_MODE: str
    LOG_FILE_PATH: str
    DEFAULT_CWD: str
    TTS_PROVIDER: str
    TTS_CONFIG: dict

settings = Settings(LOG_MODE, LOG_FILE_PATH, DEFAULT_CWD, TTS_PROVIDER, TTS_CONFIG)     
