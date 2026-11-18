"""Text utilities for TTS chunking and sentence accumulation."""

import re

from src.config.logger import get_logger

logger = get_logger("voice.text_utils")


def accumulate_sentences(chunks):
    """
    chunks: iterable of strings (LLM stream)
    yields: complete sentences/phrases ready for TTS
    """
    buffer = ""
    # Saw .!? — flush at the next whitespace instead of immediately, so
    # "tracker.py" / "3.5" stay whole and the boundary space lands at the START
    # of the next chunk (consumers concatenate chunks verbatim).
    pending = False

    for chunk in chunks:
        for char in chunk:
            if pending and char.isspace():
                if buffer:
                    yield buffer
                buffer = ""
                pending = False

            buffer += char

            # Hard break - always split
            if char in (".", "!", "?"):
                pending = True

            # Soft break - only if buffer is large enough
            elif char == "," and len(buffer) > 60:
                yield buffer
                buffer = ""
                pending = False

            # Force break on space if too long
            elif char == " " and len(buffer) > 120:
                yield buffer
                buffer = ""
                pending = False

    # Flush remaining
    if buffer:
        yield buffer


async def async_accumulate_sentences(chunks):
    """Async twin of accumulate_sentences for async LLM streams."""
    buffer = ""
    # Saw .!? — flush at the next whitespace instead of immediately, so
    # "tracker.py" / "3.5" stay whole and the boundary space lands at the START
    # of the next chunk (consumers concatenate chunks verbatim).
    pending = False

    async for chunk in chunks:
        for char in chunk:
            if pending and char.isspace():
                if buffer:
                    yield buffer
                buffer = ""
                pending = False

            buffer += char

            # Hard break - always split
            if char in (".", "!", "?"):
                pending = True

            # Soft break - only if buffer is large enough
            elif char == "," and len(buffer) > 60:
                yield buffer
                buffer = ""
                pending = False

            # Force break on space if too long
            elif char == " " and len(buffer) > 120:
                yield buffer
                buffer = ""
                pending = False

    # Flush remaining
    if buffer:
        yield buffer


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9\s,.?!\'\"]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text

def _demo() -> None:
    """Self-check: chunks must re-join into the original text, spaces intact."""
    src = "Check src/utils/text_utils.py It measures STT, LLM TTFT, and TTS. Done!"
    chunks = list(accumulate_sentences([c for c in src]))
    assert "".join(chunks) == src, chunks
    # "…text_utils.py" must not be split at the extension dot.
    assert any("text_utils.py" in c for c in chunks), chunks
    # Boundary space is carried on the next chunk, never dropped.
    assert chunks[-1].startswith(" "), chunks
    print("ok:", chunks)


if __name__ == "__main__":
    _demo()
