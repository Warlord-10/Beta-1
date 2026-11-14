"""src.skills — Markdown-based reusable playbooks for the agents.

Usage:
    from src.skills import skill_index, read_skill_body
    index = skill_index()                   # active skills, for prompts
    body = read_skill_body("web_research")  # full procedure on demand
"""

from src.skills.loader import read_skill_body, skill_index

__all__ = ["skill_index", "read_skill_body"]
