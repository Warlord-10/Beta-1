from __future__ import annotations

import json
import os
from langchain_core.tools import tool

from src.config.logger import get_logger

logger = get_logger("tools.daily_memory_tools")


memory_name = "MEMORY.md"
memory_path = os.path.join("data", memory_name)

@tool
def add_to_daily_memory(memory: str) -> str:
    """Add daily memory."""

    try:
        with open(memory_path, "a") as f:
            f.write(f"- {memory}\n")
        return "Daily memory saved successfully."
    except Exception as e:
        logger.error(f"Failed to save daily memory: {e}")
        return f"Error saving daily memory: {str(e)}"


@tool
def read_daily_memory() -> str:
    """Read daily memory."""
    try:
        with open(memory_path, "r") as f:
            memory = f.read()
            if not memory:
                return "No daily memory found."
            return memory
    except FileNotFoundError:
        return "No daily memory found."
    except Exception as e:
        logger.error(f"Failed to read daily memory: {e}")
        return f"Error reading daily memory: {str(e)}"