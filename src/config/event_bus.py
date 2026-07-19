"""Event bus — decouples the pipeline (event source) from any frontend.

The pipeline ``publish()``es typed events and knows nothing about who, if
anyone, is listening. Frontends ``subscribe()`` a callback. This replaces the
old fixed ``PipelineListener`` contract: adding an event type touches only the
places that emit or care about it — never a base class or unrelated listeners.

Callbacks run on the PUBLISHING thread (a pipeline worker). A UI subscriber
must marshal onto its own loop (Textual: ``app.call_from_thread``).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from src.config.logger import get_logger

logger = get_logger("event_bus")


# ── Event types ─────────────────────────────────────────────────────
# Plain data. Add a new one here + emit it; subscribers that don't care
# simply never match it.
@dataclass
class TurnStart:
    """The bot began a response turn."""


@dataclass
class Chunk:
    """A chunk of bot response text (usually one sentence)."""
    text: str


@dataclass
class TurnEnd:
    """The bot finished a response turn."""
    aborted: bool = False


@dataclass
class UserMessage:
    """The user said something (e.g. transcribed speech)."""
    text: str


@dataclass
class PlanReview:
    """A workflow paused for plan approval; show this plan to the user."""
    plan: dict


@dataclass
class WorkflowStatus:
    """Live snapshot of the autonomous background task, for GUI progress."""
    task: str
    plan: list
    files_changed: list
    status: str  # running | done | failed | cancelled


Event = object  # any of the dataclasses above
Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Subscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a callback. Returns an unsubscribe function."""
        with self._lock:
            self._subs.append(callback)
        return lambda: self.unsubscribe(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        with self._lock:
            if callback in self._subs:
                self._subs.remove(callback)

    def publish(self, event: Event) -> None:
        """Fan the event out to every subscriber. Never raises — a broken
        subscriber is logged, not propagated back into the pipeline."""
        with self._lock:
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(event)
            except Exception:
                logger.exception("event subscriber failed for %r", event)


# Module-level singleton, mirroring global_queues / global_events.
EVENT_BUS = EventBus()


def _demo() -> None:
    """Self-check: published events reach subscribers; a broken one is isolated."""
    seen = []
    unsub = EVENT_BUS.subscribe(seen.append)
    EVENT_BUS.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))  # broken sub
    EVENT_BUS.publish(Chunk("hi"))
    EVENT_BUS.publish(TurnEnd())
    assert [type(e).__name__ for e in seen] == ["Chunk", "TurnEnd"], seen
    assert seen[0].text == "hi"
    unsub()
    EVENT_BUS.publish(Chunk("after-unsub"))
    assert len(seen) == 2, seen  # unsubscribed callback stopped receiving
    print("event_bus demo ok")


if __name__ == "__main__":
    _demo()
