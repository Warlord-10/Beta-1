"""Cost Tracker — tracks input/output token usage per model.

Uses LangChain's callback system so tracking is automatic for every
LLM call routed through the factory.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.config.logger import get_logger

logger = get_logger("llms.cost_tracker")


# ── Data containers ──────────────────────────────────────────────────

@dataclass
class ModelUsage:
    """Token counts for a single model."""
    input_tokens: int = 0
    output_tokens: int = 0
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

    # ── Recording ────────────────────────────────────────────────────

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Add token counts for *model*."""
        with self._lock:
            if model not in self._usage:
                self._usage[model] = ModelUsage()
            entry = self._usage[model]
            entry.input_tokens += input_tokens
            entry.output_tokens += output_tokens
            entry.call_count += 1

    # ── Querying ─────────────────────────────────────────────────────

    def get_usage(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Return usage dict for one model or all models.

        Returns:
            {
              "model_name": {
                "input_tokens": int,
                "output_tokens": int,
                "total_tokens": int,
                "call_count": int,
              },
              ...
            }
        """
        with self._lock:
            if model:
                entry = self._usage.get(model, ModelUsage())
                return {
                    model: {
                        "input_tokens": entry.input_tokens,
                        "output_tokens": entry.output_tokens,
                        "total_tokens": entry.total_tokens,
                        "call_count": entry.call_count,
                    }
                }
            return {
                m: {
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "total_tokens": u.total_tokens,
                    "call_count": u.call_count,
                }
                for m, u in self._usage.items()
            }

    def get_summary(self) -> str:
        """Human-readable summary of all token usage."""
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
        """Clear all recorded usage."""
        with self._lock:
            self._usage.clear()


# ── LangChain Callback Handler ───────────────────────────────────────

class CostTrackerCallback(BaseCallbackHandler):
    """LangChain callback that feeds token usage into a CostTracker."""

    def __init__(self, tracker: CostTracker, model_name: str) -> None:
        super().__init__()
        self._tracker = tracker
        self._model_name = model_name

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Called when an LLM call finishes — extract token usage."""
        for gen_list in response.generations:
            for gen in gen_list:
                usage = {}
                # Try generation_info first (most providers)
                if hasattr(gen, "generation_info") and gen.generation_info:
                    usage = gen.generation_info.get("usage_metadata", {})

                # Fallback: llm_output on the response
                if not usage and response.llm_output:
                    usage = response.llm_output.get("usage_metadata", {})
                    if not usage:
                        usage = response.llm_output.get("token_usage", {})

                input_tokens = (
                    usage.get("input_tokens", 0)
                    or usage.get("prompt_tokens", 0)
                    or usage.get("prompt_token_count", 0)
                )
                output_tokens = (
                    usage.get("output_tokens", 0)
                    or usage.get("completion_tokens", 0)
                    or usage.get("candidates_token_count", 0)
                )

                if input_tokens or output_tokens:
                    self._tracker.record(
                        self._model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    logger.debug(
                        "Token usage [%s]: %d in / %d out",
                        self._model_name, input_tokens, output_tokens,
                    )


# ── Module-level singleton ───────────────────────────────────────────

cost_tracker = CostTracker()
