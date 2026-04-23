"""Text utilities for TTS chunking and sentence accumulation."""

import re
from typing import Generator, Iterable

from src.config.logger import get_logger

logger = get_logger("voice.text_utils")


def accumulate_sentences(chunks):
    """
    chunks: iterable of strings (LLM stream)
    yields: complete sentences/phrases ready for TTS
    """
    buffer = ""
    
    for chunk in chunks:        # ← iterates over LLM stream
        for char in chunk:      # ← iterates over chars in each chunk
            buffer += char
            
            # Hard break - always split
            if char in (". ", "!", "?"):
                if buffer.strip():
                    yield buffer.strip()
                buffer = ""
            
            # Soft break - only if buffer is large enough
            elif char == "," and len(buffer) > 80:
                if buffer.strip():
                    yield buffer.strip()
                buffer = ""
            
            # Force break on space if too long
            elif char == " " and len(buffer) > 150:
                if buffer.strip():
                    yield buffer.strip()
                buffer = ""
    
    # Flush remaining
    if buffer.strip():
        yield buffer.strip()

def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9\s,.?!\'\"]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text

def clean_text_with_hindi(text: str) -> str:
    if not text:
        return ""

    pattern = r'[^a-zA-Z0-9\s,.\u0900-\u097F]'
    text = re.sub(pattern, '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text
    