"""Voice Activity Detection using Silero VAD."""

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from src.config.logger import get_logger

logger = get_logger("asr.vad")

class VoiceActivityDetector:
    """Wraps Silero VAD for detecting speech in numpy audio arrays."""

    def __init__(self, threshold: float = 0.5):
        try:
            self.model = load_silero_vad()
            self.threshold = threshold
            logger.info(f"Loaded Silero VAD model (threshold={threshold})")
        except NameError:
            raise ImportError("Please install silero-vad first: pip install silero-vad")

    def contains_speech(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        audio_tensor = torch.from_numpy(audio)
        
        try:
            timestamps = get_speech_timestamps(
                audio_tensor, 
                self.model, 
                threshold=self.threshold,
                sampling_rate=sample_rate,
                return_seconds=False
            )
            return len(timestamps) > 0
        except Exception as e:
            logger.error(f"VAD Error: {e}")
            return False
