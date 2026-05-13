from langchain_core.tools import tool
from ddgs import DDGS

# @tool
# def search_web(query: str) -> str:
#     """Search the web for information."""
#     search = DuckDuckGoSearchRun()
#     return search.invoke(query)

@tool
def regular_search(query: str) -> list[dict[str, str]]:
    """Search the web for information and returns the text results."""
    results = DDGS().text(query, max_results=5, region="in-hi", safesearch="off", backend="brave")
    return results

@tool
def advanced_search(query: str, type: str) -> list[dict[str, str]]:
    """Search the web for information using advanced filters based on type and return the results
    type: Literal [images, videos, news]
    """
    if type == "images":
        results = DDGS().images(query, max_results=5, region="in-hi", safesearch="off")
    elif type == "videos":
        results = DDGS().videos(query, max_results=5, region="in-hi", safesearch="off")
    elif type == "news":
        results = DDGS().news(query, max_results=5, region="in-hi", safesearch="off")
    return results

@tool
def extract_text(url: str) -> list[dict[str, str]]:
    """Extract text from a URL and returns the text."""
    result = DDGS().extract(url, fmt="text_markdown")
    return result