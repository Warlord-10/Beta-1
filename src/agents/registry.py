"""Agent registry — single source of truth for sub-agents the supervisor can dispatch to.

Each entry maps an agent key to a short capability description. The supervisor
reads this both to build its routing prompt and to wire conditional edges in
the sub-graph. Adding a new agent = one line here + registering its node in
`build_supervisor_graph`.
"""

from __future__ import annotations

AGENT_REGISTRY: dict[str, str] = {
    "coding_agent": "Writes/edits code, reads/writes files, lints, debugs, searches files and content.",
    "research_agent": "Searches the web, extracts page content, cross-references sources, and synthesizes research findings.",
}


def registry_prompt() -> str:
    """Render the registry as a bulleted list for inclusion in LLM prompts."""
    return "\n".join(f"  • **{name}** — {desc}" for name, desc in AGENT_REGISTRY.items())
