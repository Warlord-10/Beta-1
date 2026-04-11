"""src.llms — Centralized LLM management.

Public API:
    llm_factory                     → LLMFactory singleton
    LLMFactory                      → class for creating LLM instances
    cost_tracker                    → CostTracker singleton
    MODEL_REGISTRY                  → dict of aliases
"""

from src.llms.factory import LLMFactory, llm_factory
from src.llms.cost_tracker import cost_tracker, CostTracker
from src.llms.registry import MODEL_REGISTRY, resolve_model

__all__ = [
    "LLMFactory",
    "llm_factory",
    "cost_tracker",
    "CostTracker",
    "MODEL_REGISTRY",
    "resolve_model",
]
