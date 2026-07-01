"""Factory to dynamically select the best ASR provider based on hardware."""

import platform
from typing import Any, Dict

from src.asr.base import BaseASR
from src.config.logger import get_logger

logger = get_logger("asr.factory")

def get_asr_engine(config: Dict[str, Any] = None) -> BaseASR:
    if config.get("provider", "mlx") == "mlx":
        from src.asr.mlx_provider import MLXProviderASR
        return MLXProviderASR(**config)
