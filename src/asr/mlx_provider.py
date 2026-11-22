"""MLX speech-to-text (mlx-audio) for Apple Silicon."""

import re
import warnings

import numpy as np
from src.asr.base import BaseASR
from src.config.logger import get_logger
from src.config.settings import SETTINGS
import mlx_audio.stt.utils as utils
import mlx.core as mx

logger = get_logger("asr.mlx")

# Qwen3-ASR models (e.g. Rumble) answer "language <name><asr_text><text>" when
# detecting the language. mlx-audio drops <asr_text> as a special token before
# it can split on it, so the "language <name>" part is left in the text.
_LANGUAGE_PREFIX = re.compile(r"^language \S+\s*")

# Known-good models (a bare name means mlx-community/<name>):
#   parakeet-tdt_ctc-110m, parakeet-tdt-0.6b-v3, nemotron-3.5-asr-streaming-0.6b(-8bit)
#   FluidVoice-Labs/fluid-speech-pro-mlx   English + 24 European; option: clean_mode
#   TypeWhisper/Rumble-2-Flash-8bit        45 languages incl. Hindi; options: language, max_tokens

class MLXProviderASR(BaseASR):
    def __init__(self, model_name="parakeet-tdt_ctc-110m", provider=None, **generate_kwargs) -> None:
        # Remaining STT_CONFIG keys go to generate(), e.g. Rumble's language
        # or Fluid Speech Pro's clean_mode.
        self.generate_kwargs = generate_kwargs
        repo = model_name if "/" in model_name else f"mlx-community/{model_name}"
        try:
            self.asr = utils.load(repo)
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
                self.asr.generate(silent, **self.generate_kwargs)
            logger.info("MLX Provider ASR warmup complete")
        except Exception:
            logger.exception("MLX Provider ASR warmup failed")
        
    def transcribe(self, audio: np.ndarray) -> str:
        audio = audio.astype(np.float32)
        audio = mx.array(audio)

        result = self.asr.generate(audio, **self.generate_kwargs)
        text = result.text.strip()
        if hasattr(self.asr, "extract_language"):   # Qwen3-ASR family only
            text = _LANGUAGE_PREFIX.sub("", text)

        logger.debug(f"Transcribed (mlx provider): {text}")
        return text
        