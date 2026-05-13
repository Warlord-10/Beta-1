"""Search tools — web search, content extraction, and advanced search."""

from src.tools.search_tools.browse_web import (
    advanced_search,
    extract_text,
    regular_search,
)

# All tools for the research agent
search_tools = [regular_search, advanced_search, extract_text]

# Lightweight subset for the chat agent (quick lookups only)
chat_search_tools = [regular_search]

__all__ = [
    "regular_search",
    "advanced_search",
    "extract_text",
    "search_tools",
    "chat_search_tools",
]
