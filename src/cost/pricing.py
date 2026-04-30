"""LLM pricing lookup + cost calculation.

Reads optional `pricing` blocks from `config/models.json` (USD per 1M tokens).
Missing pricing -> cost 0.0 with a one-time warning per registry key.
"""

from __future__ import annotations

from typing import Optional

from src.llms.registry import MODEL_REGISTRY
from src.config.logger import get_logger

logger = get_logger("cost.pricing")

_warned: set[str] = set()


def get_pricing(registry_key: str) -> Optional[dict]:
    config = getattr(MODEL_REGISTRY, registry_key, None)
    if not isinstance(config, dict):
        return None
    pricing = config.get("pricing")
    return pricing if isinstance(pricing, dict) else None


def calculate_cost(
    registry_key: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
) -> float:
    pricing = get_pricing(registry_key)
    if not pricing:
        if registry_key not in _warned:
            logger.warning("No pricing configured for '%s' — cost will be 0.0", registry_key)
            _warned.add(registry_key)
        return 0.0

    input_rate = float(pricing.get("input", 0.0))
    output_rate = float(pricing.get("output", 0.0))
    cached_rate = float(pricing.get("cached", input_rate))

    fresh_input = max(0, input_tokens - cached_tokens)
    cost = (
        fresh_input / 1_000_000 * input_rate
        + cached_tokens / 1_000_000 * cached_rate
        + output_tokens / 1_000_000 * output_rate
    )
    return round(cost, 8)
