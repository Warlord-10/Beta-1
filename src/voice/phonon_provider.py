from __future__ import annotations

import numpy as np

import ptts
from typing import Iterator

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
from src.voice.base_provider import BaseTTS
from src.config.settings import SETTINGS

logger = get_logger("voice.phonon")

# Gradium Phonon via its native runtime (ptts): no MLX port exists, and ptts
# streams on CPU and spells out numbers/dates, which the transformers port doesn't.
class PhononTTS(BaseTTS):
    def __init__(
        self,
        model_name: str = "hf://gradium/phonon-31m-en",
        voice_name: str = "Easton",
        lang: str = "en",
        quant: str = "q8",
        **kwargs,
    ) -> None:
        self.sample_rate = SETTINGS.TTS_SAMPLE_RATE
        self.voice_name = voice_name

        logger.info("Initializing Phonon TTS (model=%s, voice=%s)", model_name, voice_name)
        self.tts = ptts.TTS(model_name, lang=lang, quant=quant)
        if self.tts.sample_rate != self.sample_rate:
            logger.warning(
                "%s outputs %d Hz but TTS_SAMPLE_RATE is %d — set TTS_SAMPLE_RATE to %d",
                model_name, self.tts.sample_rate, self.sample_rate, self.tts.sample_rate,
            )
        self._warmup()
        logger.info("Phonon TTS ready")

    def _warmup(self) -> None:
        try:
            for _ in self.tts.stream("warmup.", voice=self.voice_name):
                pass
        except Exception:
            logger.exception("Phonon warmup failed")

    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        text = clean_text(text)
        if not text:
            return

        try:
            logger.debug("Synthesizing: %r", text[:60])
            for pcm in self.tts.stream(text, voice=self.voice_name):
                yield pcm

        except Exception:
            logger.exception("Phonon synthesis failed for: %r", text[:60])
