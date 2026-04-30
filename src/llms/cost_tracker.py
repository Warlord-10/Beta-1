"""Cost Tracker — tracks input/output token usage per model.

Uses LangChain's callback system so tracking is automatic for every
LLM call routed through the factory. Also persists each call to the
SQLite-backed `cost_store` with an estimated dollar cost.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.cost.pricing import calculate_cost
from src.cost.store import cost_store

logger = get_logger("llms.cost_tracker")


# ── Data containers ──────────────────────────────────────────────────

@dataclass
class ModelUsage:
    """Token counts for a single model."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    call_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ── Tracker ──────────────────────────────────────────────────────────

class CostTracker:
    """Thread-safe, per-model token usage accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage: Dict[str, ModelUsage] = {}

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> None:
        with self._lock:
            if model not in self._usage:
                self._usage[model] = ModelUsage()
            entry = self._usage[model]
            entry.input_tokens += input_tokens
            entry.output_tokens += output_tokens
            entry.cached_tokens += cached_tokens
            entry.call_count += 1

    def get_usage(self, model: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if model:
                entry = self._usage.get(model, ModelUsage())
                return {
                    model: {
                        "input_tokens": entry.input_tokens,
                        "output_tokens": entry.output_tokens,
                        "cached_tokens": entry.cached_tokens,
                        "total_tokens": entry.total_tokens,
                        "call_count": entry.call_count,
                    }
                }
            return {
                m: {
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cached_tokens": u.cached_tokens,
                    "total_tokens": u.total_tokens,
                    "call_count": u.call_count,
                }
                for m, u in self._usage.items()
            }

    def get_summary(self) -> str:
        with self._lock:
            if not self._usage:
                return "No LLM usage recorded yet."
            lines = ["═══ LLM Token Usage ═══"]
            total_in = total_out = 0
            for model, u in sorted(self._usage.items()):
                lines.append(
                    f"  {model}: "
                    f"{u.input_tokens:,} in / {u.output_tokens:,} out / "
                    f"{u.total_tokens:,} total  ({u.call_count} calls)"
                )
                total_in += u.input_tokens
                total_out += u.output_tokens
            lines.append(
                f"  ── TOTAL: {total_in:,} in / {total_out:,} out / "
                f"{total_in + total_out:,} total"
            )
            return "\n".join(lines)

    def reset(self) -> None:
        with self._lock:
            self._usage.clear()


# ── Helpers ──────────────────────────────────────────────────────────

def _start_of_day_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _daily_budget() -> float | None:
    val = getattr(SETTINGS, "daily_budget_usd", None)
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ── LangChain Callback Handler ───────────────────────────────────────

class CostTrackerCallback(BaseCallbackHandler):
    """LangChain callback: captures token usage, persists per-call cost."""

    _budget_warned_today: tuple[str, bool] | None = None

    def __init__(
        self,
        tracker: CostTracker,
        registry_key: str,
        model_name: str,
        provider: str,
    ) -> None:
        super().__init__()
        self._tracker = tracker
        self._registry_key = registry_key
        self._model_name = model_name
        self._provider = provider

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for gen_list in response.generations:
            for gen in gen_list:

                usage = gen.message.usage_metadata
                input_tokens = usage['input_tokens']
                output_tokens = usage['output_tokens']
                cached_tokens = usage['input_token_details']['cache_read']

                if not (input_tokens or output_tokens):
                    continue

                self._tracker.record(
                    self._registry_key,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                )

                estimated_cost = calculate_cost(
                    self._registry_key,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                )

                try:
                    cost_store.record(
                        registry_key=self._registry_key,
                        model_name=self._model_name,
                        provider=self._provider,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cached_tokens=cached_tokens,
                        estimated_cost=estimated_cost,
                    )
                except Exception:
                    logger.exception("Failed to persist cost row for %s", self._registry_key)

                logger.debug(
                    "Token usage [%s]: %d in / %d out / %d cached / $%.6f",
                    self._registry_key, input_tokens, output_tokens,
                    cached_tokens, estimated_cost,
                )

                self._maybe_warn_budget()

    def _maybe_warn_budget(self) -> None:
        budget = _daily_budget()
        if not budget or budget <= 0:
            return
        try:
            spent = cost_store.total_cost(since=_start_of_day_utc())
        except Exception:
            return
        if spent < budget:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        cls = type(self)
        if cls._budget_warned_today and cls._budget_warned_today[0] == today:
            return
        cls._budget_warned_today = (today, True)
        logger.warning(
            "Daily LLM budget exceeded: $%.4f spent today (budget $%.4f)",
            spent, budget,
        )


cost_tracker = CostTracker()
