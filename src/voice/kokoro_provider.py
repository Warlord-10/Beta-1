
from __future__ import annotations

import numpy as np

from kokoro import KPipeline
from typing import Iterator

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
from src.voice.base_provider import BaseTTS

logger = get_logger("voice.kokoro")

class KokoroTTS(BaseTTS):
    def __init__(self, voice_name: str = "af_heart", speed: float = 1.3) -> None:
        self.sample_rate = 24000
        self.voice_name = voice_name
        self.speed = speed

        lang_code = voice_name[0] if voice_name else "a"
        logger.info("Initializing Kokoro TTS (lang=%s, voice=%s)", lang_code, voice_name)
        self.pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        self._warmup()
        logger.info("Kokoro TTS ready")

    def _warmup(self) -> None:
        """Force voice tensor load + first-call graph build at startup."""
        try:
            for _ in self.pipeline(
                "warmup.",
                voice=self.voice_name,
                speed=self.speed,
                split_pattern=r"\n+",
            ):
                pass
        except Exception:
            logger.exception("Kokoro warmup failed")

    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        """
        Yields numpy audio chunks for the given text.
        This is a generator — iterate it, don't call it like a function.
        """

        text = clean_text(text)

        try:
            logger.debug("Synthesizing: %r", text[:60])
            for _gs, _ps, audio in self.pipeline(
                text,
                voice=self.voice_name,
                speed=self.speed,
                split_pattern=r'\n+',
            ):
                yield audio

        except Exception:
            logger.exception("Kokoro synthesis failed for: %r", text[:60])
