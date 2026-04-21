"""MLX-Whisper STT implementation optimized for Apple Silicon."""

import numpy as np
import warnings
from src.asr.base import BaseASR
from src.config.logger import get_logger

logger = get_logger("asr.mlx")

class MLXWhisperASR(BaseASR):
    """ASR implementation using mlx-whisper for Mac."""

    def __init__(self, model_path: str = "mlx-community/whisper-base-mlx"):
        try:
            import mlx_whisper
            self.asr = mlx_whisper
        except ImportError:
            raise ImportError("Please install mlx-whisper first: pip install mlx-whisper")
            
        self.model_path = model_path
        logger.info(f"Loaded mlx-whisper with model: {self.model_path}")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        audio = audio.astype(np.float32)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = self.asr.transcribe(audio, path_or_hf_repo=self.model_path)
            
        text = result.get("text", "").strip()
        logger.debug(f"Transcribed (mlx): {text}")
        return text
