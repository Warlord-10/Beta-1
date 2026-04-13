"""Kokoro TTS Provider."""

from __future__ import annotations

from typing import Optional
import numpy as np

try:
    from kokoro import KPipeline
except ImportError:
    KPipeline = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

from src.config.logger import get_logger
from src.voice.base import BaseTTS

logger = get_logger("voice.kokoro")


class KokoroTTS(BaseTTS):
    """Kokoro TTS integration for Beta-1."""

    def __init__(self, voice_name: str = "af_heart", sample_rate: int = 24000, speed: float = 1.0):
        if KPipeline is None:
            raise RuntimeError("kokoro package is not installed. Run: uv sync")
            
        self.sample_rate = sample_rate
        self.voice_name = voice_name
        self.speed = speed
        
        # 'a' for American English
        # If voice_name starts with specific letter, we could dynamically detect this, but 'a' is safe default English.
        lang_code = voice_name[0] if voice_name else 'a'
        
        logger.info("Initializing Kokoro TTS pipeline (lang=%s)...", lang_code)
        self.pipeline = KPipeline(lang_code=lang_code)
        logger.info("Kokoro TTS initialized with voice: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        if not text.strip():
            return None
            
        try:
            logger.debug("Synthesizing text with Kokoro: %r", text[:50] + "...")
            generator = self.pipeline(
                text, 
                voice=self.voice_name, 
                speed=self.speed,
                split_pattern=r'\n+'
            )
            
            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(generator):
                audio_chunks.append(audio)
            
            if audio_chunks:
                # audio format is a numpy array
                return np.concatenate(audio_chunks)
            return None
        except Exception as e:
            logger.error("Kokoro synthesis failed: %s", str(e))
            return None

    def play(self, text: str, block: bool = True) -> None:
        if sd is None:
            logger.error("sounddevice package is not installed.")
            return
            
        if not text.strip():
            return
            
        try:
            generator = self.pipeline(
                text, 
                voice=self.voice_name, 
                speed=self.speed,
                split_pattern=r'\n+'
            )
            logger.info("Playing streaming audio via Kokoro.")
            # Because kokoro streams chunks, we can play them efficiently without collecting entirely first.
            chunk_queue = []
            
            # Simple async loop imitation for continuous playback if desired, or synchronous wait:
            for i, (gs, ps, audio) in enumerate(generator):
                sd.play(audio, samplerate=self.sample_rate)
                sd.wait() # Stream step by step to allow overlapping chunk generation implicitly
                
        except Exception as e:
            logger.error("Kokoro playback failed: %s", e)

    def save(self, text: str, file_path: str) -> None:
        import soundfile as sf
        audio_data = self.synthesize(text)
        if audio_data is not None:
            sf.write(file_path, audio_data, self.sample_rate)
            logger.info("Saved Kokoro TTS output to %s", file_path)
