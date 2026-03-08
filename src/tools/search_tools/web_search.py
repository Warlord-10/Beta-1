"""Tool: web_search — Search the web for information."""

from langchain_core.tools import tool


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web for a given query.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return. Defaults to 5.

    Returns:
        Search results or error description.
    """
    # Stub — integrate with a search API (Google, SerpAPI, Tavily, etc.)
    raise NotImplementedError(
        "web_search is not yet implemented. "
        "Integrate a search provider (e.g. Tavily, SerpAPI, Google Custom Search)."
    )
