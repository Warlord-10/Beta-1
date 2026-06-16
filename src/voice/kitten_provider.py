"""KittenTTS Provider."""

from __future__ import annotations

from typing import Optional
import numpy as np

try:
    from kittentts import KittenTTS
except ImportError:
    KittenTTS = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

from src.config.logger import get_logger
from src.voice.base_provider import BaseTTS

logger = get_logger("voice.kitten")


class KittenProvider(BaseTTS):
    """KittenTTS integration for Beta-1."""

    def __init__(self, model_name: str = "KittenML/kitten-tts-mini-0.8", voice_name: str = "Jasper", sample_rate: int = 24000, speed: float = 1.0):
        if KittenTTS is None:
            raise RuntimeError("kittentts package is not installed. Run: uv sync")
            
        self.sample_rate = sample_rate
        self.model_name = model_name
        self.voice_name = voice_name
        self.speed = speed
        
        logger.info("Initializing KittenTTS engine (Model: %s)...", self.model_name)
        # Initializes caching / download lazily or synchronously. No GPU backend required by default.
        self.model = KittenTTS(self.model_name)
        logger.info("KittenTTS initialized with voice: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        if not text.strip():
            return None
            
        try:
            logger.debug("Synthesizing text with KittenTTS: %r", text[:50] + "...")
            # returns numpy array
            audio = self.model.generate(
                text, 
                voice=self.voice_name, 
                speed=self.speed
            )
            return audio
        except Exception as e:
            logger.error("KittenTTS synthesis failed: %s", str(e))
            return None

    def play(self, text: str, block: bool = True) -> None:
        if sd is None:
            logger.error("sounddevice package is not installed.")
            return
            
        audio_data = self.synthesize(text)
        if audio_data is not None:
            logger.info("Playing synthesized audio via KittenTTS.")
            sd.play(audio_data, samplerate=self.sample_rate)
            if block:
                sd.wait()

    def save(self, text: str, file_path: str) -> None:
        import soundfile as sf
        audio_data = self.synthesize(text)
        if audio_data is not None:
            sf.write(file_path, audio_data, self.sample_rate)
            logger.info("Saved KittenTTS output to %s", file_path)
