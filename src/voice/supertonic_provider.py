"""Supertonic TTS Provider."""

from __future__ import annotations

from typing import Optional
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
from src.voice.base import BaseTTS

logger = get_logger("voice.supertonic")


class SupertonicTTS(BaseTTS):
    """Supertonic TTS integration for Beta-1."""

    def __init__(self, voice_name: str = "M4", sample_rate: int = 24000, speed: float = 1.0, total_steps: int = 5):
        if TTS is None:
            raise RuntimeError("supertonic package is not installed. Run: uv sync")
            
        self.sample_rate = sample_rate
        self.voice_name = voice_name
        self.speed = speed
        self.total_steps = total_steps
        
        logger.info("Initializing Supertonic TTS engine...")
        self.tts = TTS(auto_download=True)
        self.style = self.tts.get_voice_style(voice_name=self.voice_name)
        logger.info("Supertonic TTS initialized with voice style: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        if not text.strip():
            return None
            
        try:
            logger.debug("Synthesizing text with Supertonic: %r", text[:50] + "...")
            wav, duration = self.tts.synthesize(
                text, 
                voice_style=self.style, 
                speed=self.speed,
                total_steps=self.total_steps
            )
            if len(wav.shape) == 2 and wav.shape[0] == 1:
                return wav[0]
            return wav
        except Exception as e:
            logger.error("Supertonic synthesis failed: %s", str(e))
            return None

    def play(self, text: str, block: bool = True) -> None:
        if sd is None:
            logger.error("sounddevice package is not installed.")
            return
            
        audio_data = self.synthesize(text)
        if audio_data is not None:
            logger.info("Playing synthesized audio via Supertonic.")
            sd.play(audio_data, samplerate=self.sample_rate)
            if block:
                sd.wait()

    def save(self, text: str, file_path: str) -> None:
        import soundfile as sf
        audio_data = self.synthesize(text)
        if audio_data is not None:
            sf.write(file_path, audio_data, self.sample_rate)
            logger.info("Saved TTS output to %s", file_path)
