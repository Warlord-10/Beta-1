"""Prompt loader — reads markdown prompt files from the prompts directory.

Usage:
    from src.prompts import load_prompt

    system_prompt = load_prompt("chat_agent")
    # Loads src/prompts/chat_agent.md
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from src.config.logger import get_logger

logger = get_logger("prompts.loader")

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Load a markdown prompt file by name.

    Args:
        name: The prompt name (without .md extension).
              e.g. "chat_agent" loads "chat_agent.md"

    Returns:
        The prompt content as a string.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    path = PROMPTS_DIR / f"{name}.md"

    if not path.exists():
        available = [f.stem for f in PROMPTS_DIR.glob("*.md")]
        raise FileNotFoundError(
            f"Prompt '{name}' not found at {path}. "
            f"Available prompts: {', '.join(sorted(available))}"
        )

    content = path.read_text(encoding="utf-8")
    logger.debug("Loaded prompt '%s' (%d chars)", name, len(content))
    return content
