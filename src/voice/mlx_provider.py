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

# Autoregressive models (e.g. Soprano) can miss their stop token and run to
# their length limit, ending in a loop ("hahaaaa") and then static. Normal
# speech is ~0.07 s per character; anything far past this is runaway audio.
_MAX_S_PER_CHAR = 0.25
_MIN_MAX_S = 3.0


class MLXProviderTTS(BaseTTS):
    def __init__(self, model_name, provider=None, **generate_kwargs):
        # Remaining TTS_CONFIG keys go to generate(), e.g. Kokoro's
        # voice, speed and lang_code.
        self.generate_kwargs = generate_kwargs
        try:
            self.tts = load(model_name)
        except ImportError:
            raise ImportError("Please install mlx_audio first: pip install mlx_audio")

        self.sample_rate = SETTINGS.TTS_SAMPLE_RATE
        # Playback and the AEC reference both run at TTS_SAMPLE_RATE; a model
        # at another rate plays pitch-shifted (e.g. Soprano is 32 kHz).
        model_rate = getattr(self.tts, "sample_rate", self.sample_rate)
        if model_rate != self.sample_rate:
            logger.warning(
                "%s outputs %d Hz but TTS_SAMPLE_RATE is %d — set TTS_SAMPLE_RATE to %d",
                model_name, model_rate, self.sample_rate, model_rate,
            )

        self._warmup()
        logger.info("MLX Provider TTS loaded (sample_rate=%d)", self.sample_rate)

    def _warmup(self) -> None:
        try:
            for _ in self.tts.generate(text="warmup.", **self.generate_kwargs):
                pass
        except Exception:
            logger.exception("MLX Provider TTS warmup failed")

    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        text = clean_text(text)
        if not text:
            return

        logger.debug("Synthesizing: %r", text[:60])

        max_samples = int(max(_MIN_MAX_S, len(text) * _MAX_S_PER_CHAR) * self.sample_rate)
        try:
            chunks = samples = 0
            for result in self.tts.generate(text=text, **self.generate_kwargs):
                audio = result.audio
                if isinstance(audio, mx.array):
                    mx.eval(audio)
                chunk = np.asarray(audio, dtype="float32").reshape(-1)
                if chunk.size == 0:
                    continue
                if samples + chunk.size > max_samples:
                    logger.warning("TTS ran away on %r: cut at %.1fs", text[:60], max_samples / self.sample_rate)
                    yield chunk[: max_samples - samples]
                    return
                samples += chunk.size
                chunks += 1
                yield chunk

            if chunks == 0:
                logger.warning("MLX TTS produced no audio for: %r", text[:60])
        except Exception:
            logger.exception("MLX Provider TTS synthesis failed for: %r", text[:60])