#!/usr/bin/env python3
"""Cleanup log files older than 15 days in /Users/deepanshu.joshi/Documents/Projects/Beta-1/logs."""

import os
import time
from pathlib import Path

LOGS_DIR = Path("/Users/deepanshu.joshi/Documents/Projects/Beta-1/logs")
DAYS_THRESHOLD = 15
SECONDS_THRESHOLD = DAYS_THRESHOLD * 24 * 60 * 60

def cleanup_logs():
    if not LOGS_DIR.exists():
        print(f"Logs directory does not exist: {LOGS_DIR}")
        return

    now = time.time()
    deleted_count = 0
    total_freed = 0

    print(f"Starting cleanup of logs older than {DAYS_THRESHOLD} days in {LOGS_DIR}")

    for file_path in LOGS_DIR.iterdir():
        if file_path.is_file():
            try:
                mtime = file_path.stat().st_mtime
                file_age_seconds = now - mtime
                if file_age_seconds > SECONDS_THRESHOLD:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    total_freed += file_size
                    print(f"Deleted old log: {file_path.name} (age: {file_age_seconds / 86400:.1f} days)")
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}")

    print(f"Cleanup complete. Deleted {deleted_count} file(s), freed {total_freed / 1024:.2f} KB.")

if __name__ == "__main__":
    cleanup_logs()
