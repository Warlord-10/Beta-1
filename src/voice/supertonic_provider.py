"""Supertonic TTS Provider."""

from __future__ import annotations

from typing import Iterator, Optional
import numpy as np

try:
    from supertonic import TTS
except ImportError:
    TTS = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

from src.config.logger import get_logger
from src.voice.base_provider import BaseTTS

logger = get_logger("voice.supertonic")


class SupertonicTTS(BaseTTS):
    """Supertonic TTS integration for Beta-1."""

    def __init__(self, voice_name: str = "F1", speed: float = 1.0):
        self.sample_rate = 44100
        self.voice_name = voice_name
        self.speed = speed
        self.total_steps = 8
        
        logger.info("Initializing Supertonic TTS engine...")
        self.tts = TTS(auto_download=True)
        self.style = self.tts.get_voice_style(voice_name=self.voice_name)
        self._warmup()
        logger.info("Supertonic TTS initialized with voice style: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        if not text.strip():
            return

        try:
            logger.debug("Synthesizing text with Supertonic: %r", text[:50] + "...")
            wav, duration = self.tts.synthesize(
                text,
                voice_style=self.style,
                speed=self.speed,
                total_steps=self.total_steps,
                max_chunk_length=60,
                silence_duration=0,
                lang="hi"
            )
            wav = np.asarray(wav, dtype="float32").reshape(-1)
            if wav.size:
                yield wav
        except Exception:
            logger.exception("Supertonic synthesis failed for: %r", text[:50])
            return

    def _warmup(self):
        wav, duration = self.tts.synthesize(
            "warmup",
            voice_style=self.style,
            speed=self.speed,
            total_steps=self.total_steps
        )
        wav = np.asarray(wav, dtype="float32").reshape(-1)
        pass
