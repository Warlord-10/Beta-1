"""Latency Tracker — measures latency of the chat agent, TTS, and STT.

Mirrors the design of :mod:`src.llms.cost_tracker`: a thread-safe, in-memory
accumulator (per metric) plus a ``get_summary()`` for quick inspection. On top
of the in-memory stats, every sample is emitted to OpenTelemetry histograms and
(optionally) wrapped in a trace span, so the same instrumentation feeds both a
local readout and the Grafana/Prometheus/Tempo stack.

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

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from src.config.logger import get_logger
from src.observability import telemetry
from src.observability.telemetry import Metric

logger = get_logger("observability.latency_tracker")

# Per-metric ring of recent samples kept for percentile summaries. The OTel
# histograms are the source of truth for dashboards; this cap just bounds the
# in-process memory used by get_summary().
_MAX_SAMPLES = 1000


# ── Stopwatch ────────────────────────────────────────────────────────

class Stopwatch:
    """Monotonic timer. ``elapsed_ms()`` is safe to call repeatedly."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0


# ── Data container ───────────────────────────────────────────────────

@dataclass
class MetricStats:
    """Rolling latency stats for a single metric (milliseconds)."""

    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    samples: List[float] = field(default_factory=list)

    def add(self, value_ms: float) -> None:
        self.count += 1
        self.total_ms += value_ms
        self.min_ms = min(self.min_ms, value_ms)
        self.max_ms = max(self.max_ms, value_ms)
        self.samples.append(value_ms)
        if len(self.samples) > _MAX_SAMPLES:
            self.samples.pop(0)

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    def percentile(self, pct: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
        return ordered[idx]


# ── Tracker ──────────────────────────────────────────────────────────

class LatencyTracker:
    """Thread-safe, per-metric latency accumulator + OTel emitter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: Dict[str, MetricStats] = {}

    def record(self, metric: str, value_ms: float, **attributes: Any) -> None:
        """Record a single latency sample (in ms) for ``metric``.

        Updates the in-memory stats and emits to the OTel histogram. Extra
        keyword args become metric/span attributes (e.g. ``provider="kokoro"``).
        """
        with self._lock:
            entry = self._stats.get(metric)
            if entry is None:
                entry = self._stats[metric] = MetricStats()
            entry.add(value_ms)

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

    def get_summary(self) -> str:
        with self._lock:
            if not self._stats:
                return "No latency recorded yet."
            lines = ["═══ Latency (ms) ═══"]
            for metric, s in sorted(self._stats.items()):
                lines.append(
                    f"  {metric}: "
                    f"p50 {s.percentile(50):.0f} / p95 {s.percentile(95):.0f} / "
                    f"avg {s.avg_ms:.0f} / min {s.min_ms:.0f} / max {s.max_ms:.0f}  "
                    f"({s.count} samples)"
                )
            return "\n".join(lines)

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


latency_tracker = LatencyTracker()
