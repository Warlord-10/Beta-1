"""Factory to dynamically select the best ASR provider based on hardware."""

import platform
from typing import Any, Dict

from src.asr.base import BaseASR
from src.config.logger import get_logger

logger = get_logger("asr.factory")

def get_asr_engine(config: Dict[str, Any] = None) -> BaseASR:
    """Instantiate and return the best ASR engine for the current hardware.
    
    If Apple Silicon (M-series inner Mac) is detected, uses MLX-Whisper.
    Otherwise, defaults to faster-whisper.
    
    Args:
        config: Optional dictionary mapping provider kwargs.
        
    Returns:
        An instance of BaseASR.
    """
    config = config or {}
    
    is_mac = platform.system() == 'Darwin'
    is_arm = platform.processor() == 'arm'
    
    if is_mac and is_arm:
        logger.info("Apple Silicon detected. Selecting MLX-Whisper ASR engine.")
        from src.asr.mlx_provider import MLXWhisperASR

        # Extract potential custom model path from config if provided
        kwargs = {}
        if config.get("mlx_model_path"):
            kwargs["model_path"] = config["mlx_model_path"]
            
        return MLXWhisperASR(**kwargs)
        
    else:
        logger.info("Non-Apple Silicon detected. Selecting Faster-Whisper ASR engine.")
        from src.asr.whisper_provider import WhisperASR
        
        kwargs = {
            "model_size_or_path": config.get("whisper_model_size", "base"),
            "device": "auto",
            "compute_type": "default"
        }
        
        return WhisperASR(**kwargs)
