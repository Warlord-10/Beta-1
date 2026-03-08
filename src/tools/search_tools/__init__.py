"""Search tools — tools for the Search Agent."""

from src.tools.search_tools.web_search import web_search
from src.tools.search_tools.fetch_url import fetch_url
from src.tools.search_tools.read_docs import read_docs
from src.tools.search_tools.scrape_page import scrape_page

search_tools = [
    web_search,
    fetch_url,
    read_docs,
    scrape_page,
]

__all__ = [
    "search_tools",
    "web_search",
    "fetch_url",
    "read_docs",
    "scrape_page",
]
