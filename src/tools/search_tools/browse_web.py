from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool


@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    search = DuckDuckGoSearchRun()
    return search.invoke(query)

@tool
def search_results(query: str) -> str:
    search = DuckDuckGoSearchResults(output_format="json", max_results=5)
    return search.invoke(query)

