"""Telemetry — OpenTelemetry setup for the observability layer.

Initialises an OTLP exporter (traces + metrics) once on import, gated by
``SETTINGS.OBSERVABILITY_ENABLED``. Everything here is best-effort: if the
OpenTelemetry packages aren't installed or the exporter fails to start, the
helpers degrade to no-ops so the rest of the app keeps running.

The app instruments itself through :mod:`src.observability.latency_tracker`;
this module only owns the OTel wiring (tracer, meter, histograms, exporter).

Backend wiring (OTel Collector → Prometheus + Tempo → Grafana) lives in the
top-level ``observability/`` docker-compose stack.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from src.config.logger import get_logger
from src.config.settings import SETTINGS

logger = get_logger("observability.telemetry")

_SERVICE_NAME = "beta-1"

# Histogram unit — every latency we record is in milliseconds.
_LATENCY_UNIT = "ms"


# ── Metric names ─────────────────────────────────────────────────────
# Central registry so instrumentation sites and dashboards agree on names.

class Metric:
    """Canonical latency metric names (dot-namespaced per OTel convention)."""

    STT_TRANSCRIBE = "stt.transcribe"      # audio buffer → final transcript
    LLM_FIRST_TOKEN = "llm.first_token"    # prompt sent → first token (TTFT)
    LLM_STREAM = "llm.stream"              # prompt sent → stream complete
    TTS_FIRST_AUDIO = "tts.first_audio"    # text in → first audio chunk (TTFB)
    TTS_SYNTHESIZE = "tts.synthesize"      # text in → synthesis complete
    TURN = "turn.e2e"                      # user message → all chunks enqueued


# ── Internal state ───────────────────────────────────────────────────

_lock = threading.Lock()
_enabled = False
_tracer = None
_meter = None
_histograms: Dict[str, Any] = {}


def is_enabled() -> bool:
    """True once OTel has been initialised and is exporting."""
    return _enabled


def _otlp_endpoint() -> Optional[str]:
    return getattr(SETTINGS, "OTEL_EXPORTER_OTLP_ENDPOINT", None) or None


def _init_telemetry() -> None:
    """Configure OTel tracer + meter providers with an OTLP exporter.

    Called once on import. No-op (with a log line) if disabled or if the
    OpenTelemetry SDK isn't available.
    """
    global _enabled, _tracer, _meter

    if not bool(getattr(SETTINGS, "OBSERVABILITY_ENABLED", False)):
        logger.info("Observability disabled (SETTINGS.OBSERVABILITY_ENABLED is false)")
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "Observability enabled but OpenTelemetry SDK not installed — "
            "latency will still be tracked in-memory. Run `uv sync` to enable export."
        )
        return

    try:
        resource = Resource.create({SERVICE_NAME: _SERVICE_NAME})
        endpoint = _otlp_endpoint()

        # Traces
        tracer_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(
            endpoint=f"{endpoint}/v1/traces" if endpoint else None
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer(_SERVICE_NAME)

        # Metrics
        metric_exporter = OTLPMetricExporter(
            endpoint=f"{endpoint}/v1/metrics" if endpoint else None
        )
        reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter(_SERVICE_NAME)

        _enabled = True
        logger.info(
            "Observability initialised — exporting OTLP to %s",
            endpoint or "default (http://localhost:4318)",
        )
    except Exception:
        logger.exception("Failed to initialise OpenTelemetry — export disabled")


def get_tracer():
    """Return the OTel tracer, or None if telemetry is disabled."""
    return _tracer


def record_histogram(metric: str, value_ms: float, attributes: Dict[str, Any]) -> None:
    """Record a latency sample to the OTel histogram for ``metric``.

    Histograms are created lazily and cached. No-op if telemetry is disabled.
    """
    if not _enabled or _meter is None:
        return
    try:
        hist = _histograms.get(metric)
        if hist is None:
            with _lock:
                hist = _histograms.get(metric)
                if hist is None:
                    hist = _meter.create_histogram(
                        name=f"{metric}.latency",
                        unit=_LATENCY_UNIT,
                        description=f"Latency of {metric} in milliseconds",
                    )
                    _histograms[metric] = hist
        hist.record(value_ms, attributes=attributes)
    except Exception:
        logger.debug("Failed to record histogram for %s", metric, exc_info=True)


# Initialise once on first import (mirrors logger / settings bootstrap).
_init_telemetry()
