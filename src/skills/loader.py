"""Skill loader — reads and writes markdown skill files with frontmatter.

A skill is a reusable playbook an agent pulls into context when a task matches.
The frontmatter (name, description, author, status, last_updated) is the source
of truth; ``SKILL_REGISTRY`` is an in-memory view of it, rebuilt from disk on
every lookup so skills created or edited by any agent are visible immediately.

    from src.skills import skill_index, read_skill_body

    index = skill_index()                  # active skills, for prompts
    body = read_skill_body("web_research")   # full procedure on demand
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from src.config.logger import get_logger

logger = get_logger("skills.loader")

SKILLS_DIR = Path(__file__).parent
SKILL_REGISTRY: list[dict[str, str]] = []

_NAME_RE = re.compile(r"^[a-z0-9_]{3,40}$")
_MAX_BODY_CHARS = 8_000
METADATA_KEYS = ("name", "description", "author", "status", "last_updated")
ACTIVE, ARCHIVED = "active", "archived"

# one global lock for every write; per-skill locks only if agents contend.
_WRITE_LOCK = threading.Lock()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body).

    2-key frontmatter (name/description), so a hand-rolled split
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


# Metadata functions
def read_skill_metadata(path: Path) -> dict[str, str]:
    """Return a skill file's metadata, filling defaults for hand-written skills."""
    meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    return {
        "name": meta.get("name", path.stem),
        "description": meta.get("description", ""),
        "author": meta.get("author", "user"),
        "status": meta.get("status", ACTIVE),
        "last_updated": meta.get("last_updated", ""),
        "path": str(path),
    }


def skill_path(skill_name: str) -> Path:
    return SKILLS_DIR / f"{skill_name}.md"


def find_skill(skill_name: str) -> dict[str, str] | None:
    return next((s for s in build_registry() if s["name"] == skill_name), None)


def read_skill_body(skill_name: str) -> str:
    skill = find_skill(skill_name)
    if skill is None:
        raise ValueError(f"Skill '{skill_name}' not found.")

    _, body = _split_frontmatter(Path(skill["path"]).read_text(encoding="utf-8"))
    return body

def write_skill(path: Path, meta: dict[str, str], body: str) -> None:
    """Write a skill atomically: temp file + rename, so a crash never leaves half a file."""
    meta = {**meta, "last_updated": datetime.now().isoformat(timespec="seconds")}
    header = "\n".join(f"{key}: {meta[key]}" for key in METADATA_KEYS)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")

    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"---\n{header}\n---\n{body.strip()}\n")
    os.replace(tmp, path)


def validate_skill(name: str, description: str | None, body: str | None) -> str | None:
    """Return an error message, or None when the input is valid."""
    if not _NAME_RE.match(name):
        return f"Invalid skill name '{name}': use lowercase letters, digits, underscores (3 to 40 chars)."
    if description is not None and (not description.strip() or "\n" in description):
        return "Description must be a single, non-empty line."
    if body is not None and len(body) > _MAX_BODY_CHARS:
        return f"Skill body is {len(body)} characters; the limit is {_MAX_BODY_CHARS}. Tighten it."
    return None


def build_registry() -> list[dict[str, str]]:
    """Rescan the skills folder and refresh SKILL_REGISTRY in place."""
    # In-place so every module that imported SKILL_REGISTRY sees the update.
    SKILL_REGISTRY[:] = [read_skill_metadata(p) for p in sorted(SKILLS_DIR.glob("*.md"))]
    return SKILL_REGISTRY


def skill_index() -> str:
    """Render active skills as ``- name — description`` lines for an LLM."""
    active = [s for s in build_registry() if s["status"] == ACTIVE]
    if not active:
        return "No skills available."
    return "\n".join(f"- {s['name']} — {s['description']}" for s in active)

