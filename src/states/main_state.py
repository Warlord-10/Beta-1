"""State schemas for Beta-1's agents."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class ChatState(TypedDict):
    """Minimal state for the chat agent — keeps its memory isolated from the
    autonomous workflow. Only `messages` is reduced (append-only)."""
    messages: Annotated[list[AnyMessage], operator.add]
    cwd: str
