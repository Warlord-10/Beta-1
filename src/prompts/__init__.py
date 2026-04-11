"""src.prompts — Markdown-based prompt loading system.

Usage:
    from src.prompts import load_prompt
    prompt = load_prompt("chat_agent")
"""

from src.prompts.loader import load_prompt

__all__ = ["load_prompt"]
