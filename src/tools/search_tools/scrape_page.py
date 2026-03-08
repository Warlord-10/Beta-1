"""Tool: scrape_page — Scrape structured data from a web page."""

from langchain_core.tools import tool


@tool
def scrape_page(url: str, selector: str = "body") -> str:
    """Scrape text content from a web page, optionally filtered by CSS-like tag.

    This is a lightweight scraper using only stdlib. For complex CSS selectors,
    consider integrating BeautifulSoup.

    Args:
        url: The URL to scrape.
        selector: A simple tag name to extract (e.g. "article", "main", "body").

    Returns:
        Scraped text content or error description.
    """
    try:
        import urllib.request
        import re

        req = urllib.request.Request(url, headers={"User-Agent": "Beta-1/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Try to extract the target tag's content
        pattern = rf"<{selector}[^>]*>(.*?)</{selector}>"
        match = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            fragment = match.group(1)
        else:
            fragment = html  # fallback to full page

        # Strip remaining HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", fragment, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > 30_000:
            text = text[:30_000] + "\n\n… (truncated)"

        return f"🕷️ Scraped <{selector}> from {url}:\n\n{text}"
    except Exception as e:
        return f"❌ Error scraping `{url}`: {e}"
