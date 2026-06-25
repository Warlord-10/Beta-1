"""MLX-Whisper STT implementation optimized for Apple Silicon."""

import numpy as np
import warnings
from src.asr.base import BaseASR
from src.config.logger import get_logger
from src.config.settings import SETTINGS
import mlx_audio.stt.utils as utils
import mlx.core as mx
import warnings

logger = get_logger("asr.mlx")

model_bank = [
    "whisper-small-mlx",
    "parakeet-tdt_ctc-110m", 
    "parakeet-tdt-0.6b-v3",
    "nemotron-3.5-asr-streaming-0.6b",
    "nemotron-3.5-asr-streaming-0.6b-8bit"
]

class MLXProviderASR(BaseASR):
    def __init__(self, model_name="parakeet-tdt_ctc-110m", **kwargs) -> None:
        try:
            self.asr = utils.load(f"mlx-community/{model_name}")
            self.sample_rate = SETTINGS.STT_SAMPLE_RATE
            self._warmup()
            logger.info("MLX Provider ASR loaded successfully")
        except ImportError:
            raise ImportError("Please install mlx_audio first: pip install mlx_audio")

    def _warmup(self) -> None:
        try:
            silent = np.zeros(self.sample_rate, dtype=np.float32)
            silent = mx.array(silent)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.asr.generate(silent)
            logger.info("MLX Provider ASR warmup complete")
        except Exception:
            logger.exception("MLX Provider ASR warmup failed")
        
    def transcribe(self, audio: np.ndarray) -> str:
        audio = audio.astype(np.float32)
        audio = mx.array(audio)

        result = self.asr.generate(audio)
        text = result.text.strip()

        logger.debug(f"Transcribed (mlx provider): {text}")
        return text
        