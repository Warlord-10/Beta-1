"""Factory for initializing the appropriate TTS engine."""

from typing import Dict, Any
from src.config.logger import get_logger
from src.voice.base_provider import BaseTTS

logger = get_logger("voice.factory")

def get_tts_engine(config: Dict[str, Any] = {}) -> BaseTTS:
    provider = config.get("provider", "kokoro").lower().strip()
    
    if provider == "supertonic":
        from src.voice.supertonic_provider import SupertonicTTS
        return SupertonicTTS(**config)
    elif provider == "kokoro":
        from src.voice.kokoro_provider import KokoroTTS
        return KokoroTTS(**config)
    elif provider == "mlx":
        from src.voice.mlx_provider import MLXProviderTTS
        return MLXProviderTTS(**config)
    else:
        return None
        # raise ValueError(f"Unknown TTS provider: {provider}")
