"""Cost Tracker — LangChain callback that persists every LLM call's token
usage and estimated dollar cost to the SQLite-backed `cost_store`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.cost.pricing import calculate_cost
from src.cost.store import cost_store

logger = get_logger("llms.cost_tracker")


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
        registry_key: str,
        model_name: str,
        provider: str,
    ) -> None:
        super().__init__()
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

