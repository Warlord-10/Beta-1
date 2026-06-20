# Observability — Voice Pipeline Latency

Measures the latency of the three pipeline stages — **STT**, **chat agent (LLM)**,
and **TTS** — plus end-to-end turn latency. Instrumentation is done once with
[OpenTelemetry](https://opentelemetry.io/) and exported over OTLP to a local
Grafana + Prometheus + Tempo stack.

## What gets measured

| Metric (`src.observability.Metric`) | Stage | Meaning |
|---|---|---|
| `stt.transcribe`   | STT | audio buffer → final transcript |
| `llm.first_token`  | LLM | prompt sent → **first token** (TTFT) |
| `llm.stream`       | LLM | prompt sent → stream complete |
| `tts.first_audio`  | TTS | text in → **first audio chunk** (TTFB) |
| `tts.synthesize`   | TTS | text in → synthesis complete |
| `turn.e2e`         | Turn | user message → all chunks enqueued |

`TTFT` (`llm.first_token`) and `TTFB` (`tts.first_audio`) are the numbers a user
actually *feels* in a streaming voice agent — watch those first.

Every sample is also kept in-process; `latency_tracker.get_summary()` prints
p50/p95/avg/min/max without needing the stack running.

## How it's wired

```
app ──OTLP/HTTP:4318──▶ OTel Collector ──▶ Prometheus  (metrics, p50/p95/p99)
                                       └──▶ Tempo       (per-turn traces)
                                                ▲
                                                └── Grafana (dashboards)
```

The OTel layer is **best-effort**: if the SDK isn't installed or the collector
is down, the app logs a line and keeps running — latency is still tracked
in-memory.

## Running it

1. Start the stack:
   ```bash
   cd observability && docker compose up -d
   ```
2. Enable export in `config/settings.json`:
   ```json
   "OBSERVABILITY_ENABLED": true,
   "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"
   ```
3. Run the app (`python main.py`) and talk to it.
4. Open Grafana at **http://localhost:3000** → dashboard **“Beta-1 — Voice
   Pipeline Latency”** (anonymous admin, no login). Traces: Explore → Tempo.

Tear down with `docker compose down` (add `-v` to drop trace storage).

## Adding a new metric

1. Add a name constant to `Metric` in `src/observability/telemetry.py`.
2. At the call site, either wrap a block:
   ```python
   from src.observability import Metric, latency_tracker
   with latency_tracker.measure(Metric.MY_THING, provider="x"):
       do_work()
   ```
   or, for a mid-stream marker (like TTFT), use a `Stopwatch`:
   ```python
   from src.observability import Metric, Stopwatch, latency_tracker
   sw = Stopwatch()
   ...
   latency_tracker.record(Metric.MY_THING, sw.elapsed_ms())
   ```
3. Add a panel to `grafana/provisioning/dashboards/beta1-latency.json`. The
   Prometheus metric name is the dotted name with dots→underscores and a
   `_milliseconds` unit suffix, e.g. `my.thing` → `my_thing_latency_milliseconds`
   (`_bucket` / `_count` / `_sum` series).

> **Note** on metric names: Prometheus' OTLP receiver sanitizes names and appends
> the unit. If a dashboard query returns no data, check the exact series name in
> Prometheus (http://localhost:9090, *Graph* → metrics explorer).
