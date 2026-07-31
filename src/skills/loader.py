"""Skill loader — reads markdown skill files with frontmatter.

A skill is a reusable playbook the autonomous agent pulls into context when a
task matches. Same markdown pattern as prompts, plus a ``name``/``description``
frontmatter block used to advertise the skill in the system prompt.

    from src.skills import skill_index, load_skill_text

    index = skill_index()               # bullet list for the system prompt
    body = load_skill_text("web_research")   # full procedure on demand
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.config.logger import get_logger

logger = get_logger("skills.loader")

SKILLS_DIR = Path(__file__).parent


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body).

    ponytail: 2-key frontmatter (name/description), so a hand-rolled split
    beats a YAML dependency. Switch to PyYAML only if skills need nested meta.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, parts[2].lstrip("\n")


@lru_cache(maxsize=1)
def _skills() -> dict[str, tuple[str, str]]:
    """Map skill name → (description, body). One dir scan per process."""
    out: dict[str, tuple[str, str]] = {}
    for path in sorted(SKILLS_DIR.glob("*.md")):
        meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        name = meta.get("name", path.stem)
        out[name] = (meta.get("description", ""), body)
    logger.debug("Loaded %d skills", len(out))
    return out


def skill_index() -> str:
    """Render available skills as a bulleted list for the system prompt."""
    skills = _skills()
    if not skills:
        return "  (no skills available)"
    return "\n".join(f"  • **{name}** — {desc}" for name, (desc, _) in skills.items())


def load_skill_text(name: str) -> str:
    """Return a skill's full procedure body, or an error string if unknown."""
    skills = _skills()
    if name not in skills:
        return f"Unknown skill '{name}'. Available: {', '.join(sorted(skills)) or 'none'}."
    return skills[name][1]


if __name__ == "__main__":
    meta, body = _split_frontmatter("---\nname: x\ndescription: a: b\n---\nbody here")
    assert meta == {"name": "x", "description": "a: b"}, meta
    assert body == "body here", repr(body)
    assert _split_frontmatter("no frontmatter") == ({}, "no frontmatter")
    print("skills loader self-check ok;", len(_skills()), "skills found")
