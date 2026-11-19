"""Per-day JSONL transcript of an agent's conversation.

File: ``chats/<YYYY-MM-DD>/<agent>.jsonl`` — one record per line, append-only:

- ``{"type": "message", "message": {...}}``  a LangChain message (messages_to_dict)
- ``{"type": "turn", "context_tokens": N, "day_tokens": M}``  token counts after a turn
- ``{"type": "compaction", "messages": [...]}``  the new context after a compaction
  (summary + kept messages); restore starts from the latest one
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from langchain_core.messages import AnyMessage, messages_from_dict, messages_to_dict

_CHATS_DIR = Path(__file__).resolve().parents[2] / "chats"


class Transcript:
    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name

    @property
    def path(self) -> Path:
        # Resolved per write, so a session running past midnight rolls over.
        return _CHATS_DIR / str(date.today()) / f"{self.agent_name}.jsonl"

    def append(self, record: dict) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), **record}) + "\n")

    def add_messages(self, messages: list[AnyMessage]) -> None:
        for msg in messages_to_dict(messages):
            self.append({"type": "message", "message": msg})

    def restore(self) -> tuple[list[AnyMessage], int, int]:
        """Today's context (messages since the last compaction), plus the last
        recorded context and day token counts."""
        messages: list[AnyMessage] = []
        context_tokens = day_tokens = 0
        if not self.path.exists():
            return messages, context_tokens, day_tokens

        for line in self.path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["type"] == "message":
                messages.extend(messages_from_dict([record["message"]]))
            elif record["type"] == "compaction":
                messages = messages_from_dict(record["messages"])
            elif record["type"] == "turn":
                context_tokens = record["context_tokens"]
                day_tokens = record["day_tokens"]
        return messages, context_tokens, day_tokens
