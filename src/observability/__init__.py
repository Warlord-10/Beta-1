"""src.observability — Latency instrumentation for the voice pipeline.

Public API:
    latency_tracker     → LatencyTracker singleton (record / measure / get_summary)
    LatencyTracker      → class
    Stopwatch           → monotonic timer for mid-stream markers (TTFT, TTFB)
    Metric              → canonical latency metric names
    telemetry           → OpenTelemetry wiring (init on import)
"""

from src.observability import telemetry
from src.observability.latency_tracker import (
    LatencyTracker,
    Stopwatch,
    latency_tracker,
)
from src.observability.telemetry import Metric

__all__ = [
    "latency_tracker",
    "LatencyTracker",
    "Stopwatch",
    "Metric",
    "telemetry",
]
