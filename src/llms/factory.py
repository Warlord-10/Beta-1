"""LLM Factory — single entry-point for all LLM instances.

Usage:
    from src.llms import llm_factory

    llm = llm_factory.create("GEMINI_FLASH", temperature=0, max_tokens=1024)
    llm_with_tools = llm_factory.create("GEMINI_FLASH").bind_tools(my_tools)

    # Check token usage
    print(llm_factory.cost_tracker.get_summary())
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from src.llms.registry import resolve_model
from src.llms.cost_tracker import cost_tracker as _default_tracker, CostTracker, CostTrackerCallback
from src.config.logger import get_logger

logger = get_logger("llms.factory")


# ── Provider constructors ────────────────────────────────────────────

def _build_google(model: str, **kwargs: Any) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, **kwargs)


def _build_groq(model: str, **kwargs: Any) -> BaseChatModel:
    from langchain_groq import ChatGroq
    return ChatGroq(model=model, **kwargs)


def _build_openrouter(model: str, **kwargs: Any) -> BaseChatModel:
    from langchain_openrouter import ChatOpenRouter
    return ChatOpenRouter(model=model, **kwargs)

def _build_nvidia(model: str, **kwargs: Any) -> BaseChatModel:
    from langchain_nvidia import ChatNVIDIA
    return ChatNVIDIA(model=model, **kwargs)


_PROVIDER_BUILDERS = {
    "google":      _build_google,
    "groq":        _build_groq,
    "openrouter":  _build_openrouter,
    "nvidia":      _build_nvidia,
}


# ── Factory class ────────────────────────────────────────────────────

class LLMFactory:
    """Central LLM provider — single point of access for all agents.

    Resolves model aliases from the registry, builds the correct
    provider-specific LangChain model, and auto-attaches cost tracking.
    """

    def __init__(self, tracker: CostTracker | None = None) -> None:
        self._cost_tracker = tracker or _default_tracker

    @property
    def cost_tracker(self) -> CostTracker:
        """Access the cost tracker to query token usage."""
        return self._cost_tracker

    def create(
        self,
        model_name: str = "GEMINI_FLASH",
        *,
        temperature: float = 0,
        max_tokens: int | None = None,
        max_retries: int = 2,
        callbacks: list | None = None,
        **extra: Any,
    ) -> BaseChatModel:
        """Create a LangChain chat model from a registry alias.

        Args:
            model_name: An ALL_CAPS key from MODEL_REGISTRY, or a raw
                        "provider:model" string.
            temperature: Sampling temperature (default 0).
            max_tokens: Cap on generated tokens.
            max_retries: Number of retries on transient failures.
            callbacks: Additional LangChain callbacks to attach.
            **extra: Extra kwargs forwarded to the provider constructor.

        Returns:
            A ready-to-use BaseChatModel with cost tracking pre-attached.
        """
        provider, model = resolve_model(model_name)

        builder = _PROVIDER_BUILDERS.get(provider)
        if builder is None:
            supported = ", ".join(sorted(_PROVIDER_BUILDERS.keys()))
            raise ValueError(
                f"Unsupported provider '{provider}'. Supported: {supported}"
            )

        # Build kwargs
        kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_retries": max_retries,
            **extra,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # Attach cost-tracking callback
        tracker_cb = CostTrackerCallback(self._cost_tracker, model_name=model)
        all_callbacks = [tracker_cb]
        if callbacks:
            all_callbacks.extend(callbacks)
        kwargs["callbacks"] = all_callbacks

        llm = builder(model, **kwargs)
        logger.debug("Created LLM: provider=%s, model=%s", provider, model)
        return llm


# ── Module-level singleton ───────────────────────────────────────────

llm_factory = LLMFactory()