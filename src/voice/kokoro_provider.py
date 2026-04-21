"""Kokoro TTS Provider."""

from __future__ import annotations

import queue
import time
from typing import Optional

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
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
        self.audio_queue = queue.Queue()
        
        # 'a' for American English
        # If voice_name starts with specific letter, we could dynamically detect this, but 'a' is safe default English.
        lang_code = voice_name[0] if voice_name else 'a'
        
        logger.info("Initializing Kokoro TTS pipeline (lang=%s)...", lang_code)
        self.pipeline = KPipeline(lang_code=lang_code)
        logger.info("Kokoro TTS initialized with voice: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        if not text.strip():
            return None

        text = clean_text(text)
            
        try:
            logger.debug("Synthesizing text with Kokoro: %r", text[:50] + "...")
            generator = self.pipeline(
                text, 
                voice=self.voice_name, 
                speed=self.speed,
                split_pattern=r'\n+'
            )
            
            for i, (gs, ps, audio) in enumerate(generator):
                self.audio_queue.put(audio)

        except Exception as e:
            logger.error("Kokoro synthesis failed: %s", str(e))

    def play(self, text: str, block: bool = True) -> None:
        while not self.audio_queue.empty():
            audio = self.audio_queue.get()
            sd.play(audio, samplerate=self.sample_rate)
            sd.wait()             

    def stream(self):
        leftover = np.array([], dtype='float32')

        def callback(outdata, frames, time, status):
            nonlocal leftover
            needed = frames
            result = leftover

            if status:
                print(f"Status: {status}")

            # Pull from queue until we have enough samples
            while len(result) < needed:
                try:
                    chunk = self.audio_queue.get_nowait()
                    if chunk is None:
                        break
                    result = np.concatenate([result, chunk])
                except queue.Empty:
                    break

            if len(result) >= needed:
                outdata[:] = result[:needed].reshape(-1, 1)
                leftover = result[needed:]  # save the rest for next callback
            else:
                # Not enough data, fill what we have then silence
                outdata[:len(result)] = result.reshape(-1, 1)
                outdata[len(result):] = 0
                leftover = np.array([], dtype='float32')

        return sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='float32',
            callback=callback
        )

                
            
