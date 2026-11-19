"""Latency Tracker — measures latency of the chat agent, TTS, and STT.

Every sample is emitted to OpenTelemetry histograms and (optionally) wrapped
in a trace span, feeding the Grafana/Prometheus/Tempo stack.

Typical use::

    from src.observability import latency_tracker, Metric

    # Time a whole block (creates a span + records a histogram):
    with latency_tracker.measure(Metric.STT_TRANSCRIBE):
        text = model.transcribe(audio)

    # Time up to a mid-stream marker (e.g. time-to-first-token):
    sw = latency_tracker.Stopwatch()
    for i, token in enumerate(stream):
        if i == 0:
            latency_tracker.record(Metric.LLM_FIRST_TOKEN, sw.elapsed_ms())
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from src.config.logger import get_logger
from src.observability import telemetry

logger = get_logger("observability.latency_tracker")

# ── Stopwatch ────────────────────────────────────────────────────────

class Stopwatch:
    """Monotonic timer. ``elapsed_ms()`` is safe to call repeatedly."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0


# ── Tracker ──────────────────────────────────────────────────────────

class LatencyTracker:
    """Per-metric latency emitter (OTel histograms + spans)."""

    def record(self, metric: str, value_ms: float, **attributes: Any) -> None:
        """Record a single latency sample (in ms) for ``metric``.

        Emits to the OTel histogram. Extra keyword args become metric/span
        attributes (e.g. ``provider="kokoro"``).
        """
        telemetry.record_histogram(metric, value_ms, attributes)
        logger.debug("%s: %.1f ms %s", metric, value_ms, attributes or "")

    @contextmanager
    def measure(self, metric: str, **attributes: Any) -> Iterator[None]:
        """Time the wrapped block, recording a span + histogram on exit.

        The span is recorded even when the block raises, so failures still show
        up in traces with their elapsed time.
        """
        sw = Stopwatch()
        tracer = telemetry.get_tracer()
        if tracer is not None:
            with tracer.start_as_current_span(metric, attributes=attributes):
                try:
                    yield
                finally:
                    self.record(metric, sw.elapsed_ms(), **attributes)
        else:
            try:
                yield
            finally:
                self.record(metric, sw.elapsed_ms(), **attributes)


latency_tracker = LatencyTracker()
