"""Model Registry — central mapping of friendly names to provider:model.

Add new models here. Agents reference them by the ALL_CAPS alias.
Format:  "ALIAS": "provider:actual-model-name"
"""

from __future__ import annotations


# ── Registry ─────────────────────────────────────────────────────────

MODEL_REGISTRY: dict[str, str] = {
    # Gemini models
    "GEMINI_FLASH":      "google:gemini-2.0-flash",
    "GEMINI_FLASH_LITE": "google:gemini-2.0-flash-lite",
    "GEMMA_4_31B":       "google:gemma-4-31b-it",

    # Groq models
    "GROQ_LLAMA_70B":    "groq:llama-3.3-70b-versatile",

    # OpenRouter models
    "OR_NEMOTRON":       "openrouter:nvidia/nemotron-3-super-120b-a12b",
    "OR_GEMMA4":         "openrouter:google/gemma-4-31b-it:free",

    # NVIDIA models
    "DS_V4_FLASH":       "nvidia:moonshotai/kimi-k2-instruct-0905"
}


# ── Resolver ─────────────────────────────────────────────────────────

def resolve_model(name: str) -> tuple[str, str]:
    """Resolve a registry alias to (provider, model_name).

    Args:
        name: An ALL_CAPS alias from MODEL_REGISTRY, or a raw
              "provider:model" string for ad-hoc usage.

    Returns:
        Tuple of (provider, model_name).

    Raises:
        ValueError: If the alias is unknown and the string isn't
                    in "provider:model" format.
    """
    entry = MODEL_REGISTRY.get(name)

    if entry is None:
        # Allow raw "provider:model" pass-through
        if ":" in name:
            entry = name
        else:
            available = ", ".join(sorted(MODEL_REGISTRY.keys()))
            raise ValueError(
                f"Unknown model alias '{name}'. "
                f"Available aliases: {available}"
            )

    provider, _, model = entry.partition(":")
    if not provider or not model:
        raise ValueError(
            f"Invalid registry entry for '{name}': expected 'provider:model', "
            f"got '{entry}'"
        )

    return provider.lower(), model
