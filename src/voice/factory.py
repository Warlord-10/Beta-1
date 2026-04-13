"""Factory for initializing the appropriate TTS engine."""

from typing import Dict, Any
from src.config.logger import get_logger
from src.voice.base import BaseTTS

logger = get_logger("voice.factory")

def get_tts_engine(provider: str, config: Dict[str, Any]) -> BaseTTS:
    """Instantiate and return the configured TTS engine.
    
    Args:
        provider: String name of the provider ("kokoro", "supertonic").
        config: Dictionary of kwargs for the provider parameters.
        
    Returns:
        An instance of BaseTTS.
    """
    provider = provider.lower().strip()
    
    if provider == "supertonic":
        from src.voice.supertonic_provider import SupertonicTTS
        return SupertonicTTS(**config)
    elif provider == "kokoro":
        from src.voice.kokoro_provider import KokoroTTS
        return KokoroTTS(**config)
    elif provider == "kitten":
        from src.voice.kitten_provider import KittenProvider
        return KittenProvider(**config)
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")
