"""Skill tools — let any agent list, use, create, update, and archive skills.

A skill is ``src/skills/<name>.md`` with a frontmatter header:

    ---
    name: web_research
    description: One line on when to use this skill.
    author: user | agent
    status: active | archived
    last_updated: 2026-11-11T10:42:00
    ---
    <procedure body>

The frontmatter is the source of truth. The in-memory registry is rebuilt from
disk on every lookup, so a skill created or edited by any agent is visible to
every other agent immediately. Skills are never deleted, only archived.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from src.skills.loader import (
    ACTIVE,
    ARCHIVED,
    METADATA_KEYS,
    _WRITE_LOCK,
    build_registry,
    find_skill,
    read_skill_body,
    skill_path,
    skill_index,
    validate_skill,
    write_skill,
)


# Skill tools
@tool
def list_skills() -> str:
    """List the active skills (reusable step-by-step playbooks) as name — description.

    Call this before starting a complex task; if one matches, load it with load_skill.
    """
    return skill_index()


@tool
def load_skill(skill_name: str) -> str:
    """Load a skill's full procedure so you can follow it.

    Args:
        skill_name: The skill name exactly as shown by list_skills.
    """
    skill = find_skill(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found. Call list_skills to see what exists."
    if skill["status"] == ARCHIVED:
        return f"Skill '{skill_name}' is archived. Restore it with update_skill(name, status='active') if it is still useful."

    return read_skill_body(skill["name"])


@tool
def create_skill(skill_name: str, description: str, body: str) -> str:
    """Save a new reusable skill. Use it after finishing a multi-step task that is
    likely to recur and has no matching skill.

    Args:
        skill_name: Unique lowercase_snake_case name, e.g. "rename_photos_by_date".
        description: One line saying when to use this skill.
        body: The procedure in markdown: when to use it, numbered steps, expected output.
    """
    if error := validate_skill(skill_name, description, body):
        return error

    with _WRITE_LOCK:
        if find_skill(skill_name) is not None:
            return f"Skill '{skill_name}' already exists. Give this skill a new name."
        meta = {
            "name": skill_name,
            "description": description,
            "author": "agent",
            "status": ACTIVE,
        }
        write_skill(skill_path(skill_name), meta, body)

    build_registry()
    return f"Skill '{skill_name}' created."


@tool
def update_skill(
    skill_name: str,
    description: str | None = None,
    body: str | None = None,
    status: str | None = None,
) -> str:
    """Update an existing skill. Only the fields you pass are changed.

    Use it to fix a skill that misled you, add a step you discovered, or restore
    an archived skill with status="active".

    Args:
        skill_name: The skill to update.
        description: New one-line description.
        body: New full procedure (replaces the old one; load it first with load_skill).
        status: "active" or "archived".
    """
    if description is None and body is None and status is None:
        return "Nothing to update: pass description, body, or status."
    if status is not None and status not in (ACTIVE, ARCHIVED):
        return f"Invalid status '{status}': use '{ACTIVE}' or '{ARCHIVED}'."
    if error := validate_skill(skill_name, description, body):
        return error

    with _WRITE_LOCK:
        skill = find_skill(skill_name)
        if skill is None:
            return f"Skill '{skill_name}' not found. Use create_skill to add it."

        meta = {key: skill[key] for key in METADATA_KEYS}
        if description is not None:
            meta["description"] = description
        if status is not None:
            meta["status"] = status

        new_body = body if body is not None else read_skill_body(skill["name"])
        write_skill(Path(skill["path"]), meta, new_body)

    build_registry()
    return f"Skill '{skill_name}' updated."


@tool
def archive_skill(skill_name: str) -> str:
    """Archive a skill that is outdated or wrong. Archived skills are hidden from
    list_skills but kept on disk; restore one with update_skill(name, status="active").

    Args:
        skill_name: The skill to archive.
    """
    return update_skill.invoke({"skill_name": skill_name, "status": ARCHIVED})


SKILL_TOOLS = [list_skills, load_skill, create_skill, update_skill, archive_skill]
SKILL_READ_TOOLS = [list_skills, load_skill]
