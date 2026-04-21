"""Faster-Whisper STT implementation using CTranslate2."""

import numpy as np
from src.asr.base import BaseASR
from src.config.logger import get_logger

logger = get_logger("asr.whisper")

class WhisperASR(BaseASR):
    """ASR implementation using faster-whisper."""

    def __init__(self, model_size_or_path: str = "base", device: str = "auto", compute_type: str = "default"):
        """Initialize the Whisper model.
        
        Args:
            model_size_or_path: String model size (e.g., "base", "small", "large-v3") or path to CTranslate2 model.
            device: "cpu", "cuda", or "auto".
            compute_type: Float quantization to use ("float16", "int8", "default").
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("Please install faster-whisper first: pip install faster-whisper")
        
        logger.info(f"Loading faster-whisper '{model_size_or_path}' on {device} ({compute_type})...")
        self.model = WhisperModel(model_size_or_path, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe an audio array.
        
        faster_whisper expects audio as a 1D float32 numpy array at 16000Hz.
        """
        # Ensure audio is float32
        audio = audio.astype(np.float32)
        
        # We can pass the raw numpy array directly to transcribe
        segments, info = self.model.transcribe(audio, beam_size=5)
        
        # Evaluate segments generator
        text = " ".join([segment.text for segment in segments]).strip()
        logger.debug(f"Transcribed (whisper): {text}")
        return text
