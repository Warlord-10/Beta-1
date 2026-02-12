"""Shared helper utilities for file tools."""


def format_size(size_bytes: int) -> str:
    """Convert a size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
