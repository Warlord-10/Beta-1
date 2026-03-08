"""Tool: read_docs — Read and extract text from documentation pages."""

from langchain_core.tools import tool


@tool
def read_docs(url: str) -> str:
    """Read a documentation page and extract its text content.

    Strips HTML tags for cleaner output.

    Args:
        url: URL of the documentation page.

    Returns:
        Extracted text content or error description.
    """
    try:
        import urllib.request
        import re

        req = urllib.request.Request(url, headers={"User-Agent": "Beta-1/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Strip HTML tags (simple approach)
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > 30_000:
            text = text[:30_000] + "\n\n… (truncated)"

        return f"📖 Docs from {url}:\n\n{text}"
    except Exception as e:
        return f"❌ Error reading docs from `{url}`: {e}"
