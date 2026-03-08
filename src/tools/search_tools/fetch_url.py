"""Tool: fetch_url — Fetch raw content from a URL."""

from langchain_core.tools import tool


@tool
def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch the content of a URL.

    Args:
        url: The URL to fetch.
        timeout: Max seconds to wait. Defaults to 15.

    Returns:
        The page content (text) or error description.
    """
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Beta-1/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            # Truncate very large pages
            if len(content) > 50_000:
                content = content[:50_000] + "\n\n… (truncated)"
            return f"🌐 Content from {url}:\n\n{content}"
    except Exception as e:
        return f"❌ Error fetching `{url}`: {e}"
