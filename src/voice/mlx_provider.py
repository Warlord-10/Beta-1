from __future__ import annotations

import numpy as np
import mlx.core as mx

from typing import Iterator

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
from src.voice.base_provider import BaseTTS
from src.config.settings import SETTINGS
from mlx_audio.tts.utils import load

logger = get_logger("voice.mlx")


class MLXProviderTTS(BaseTTS):
    def __init__(self, model_name, **kwargs):
        try:
            self.tts = load(model_name)
        except ImportError:
            raise ImportError("Please install mlx_audio first: pip install mlx_audio")

        self.sample_rate = SETTINGS.TTS_SAMPLE_RATE

        self._warmup()
        logger.info("MLX Provider TTS loaded (sample_rate=%d)", self.sample_rate)

    def _warmup(self) -> None:
        try:
            for _ in self.tts.generate(text="warmup."):
                pass
        except Exception:
            logger.exception("MLX Provider TTS warmup failed")

    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        text = clean_text(text)
        if not text:
            return

        logger.debug("Synthesizing: %r", text[:60])

        try:
            chunks = 0
            for result in self.tts.generate(text=text):
                audio = result.audio
                if isinstance(audio, mx.array):
                    mx.eval(audio)
                chunk = np.asarray(audio, dtype="float32").reshape(-1)
                if chunk.size == 0:
                    continue
                chunks += 1
                yield chunk

            if chunks == 0:
                logger.warning("MLX TTS produced no audio for: %r", text[:60])
        except Exception:
            logger.exception("MLX Provider TTS synthesis failed for: %r", text[:60])