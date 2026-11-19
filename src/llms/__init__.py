"""src.llms — Centralized LLM management.

Public API:
    llm_factory                     → LLMFactory singleton
    LLMFactory                      → class for creating LLM instances
    MODEL_REGISTRY                  → dict of aliases
"""

from src.llms.factory import LLMFactory, llm_factory
from src.llms.registry import MODEL_REGISTRY

__all__ = [
    "LLMFactory",
    "llm_factory",
    "MODEL_REGISTRY",
]
