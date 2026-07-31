"""src.skills — Markdown-based reusable playbooks for the autonomous agent.

Usage:
    from src.skills import skill_index, load_skill_text
    index = skill_index()                 # advertise skills in the system prompt
    body = load_skill_text("web_research")  # pull a full procedure on demand
"""

from src.skills.loader import load_skill_text, skill_index

__all__ = ["skill_index", "load_skill_text"]
