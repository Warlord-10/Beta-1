"""Factory for initializing the appropriate TTS engine."""

from typing import Dict, Any
from src.config.logger import get_logger
from src.voice.base_provider import BaseTTS

logger = get_logger("voice.factory")

def get_tts_engine(provider: str = "kokoro", config: Dict[str, Any] = {}) -> BaseTTS:
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
        return None
        # raise ValueError(f"Unknown TTS provider: {provider}")
