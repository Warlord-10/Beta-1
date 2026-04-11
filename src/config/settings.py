"""Beta-1 — Central configuration / settings.

All tuneable knobs live here so you never have to hunt through code.
"""

import os
from datetime import datetime, timedelta, date

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
