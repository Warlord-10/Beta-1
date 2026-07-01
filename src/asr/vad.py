"""Voice Activity Detection using Silero VAD."""

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad, VADIterator

from src.config.logger import get_logger

logger = get_logger("asr.vad")

class VoiceActivityDetector:
    """Wraps Silero VAD for detecting speech in numpy audio arrays."""

    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        try:
            self.model = load_silero_vad(onnx=True)
            self.threshold = threshold
            self.sample_rate = sample_rate
            logger.info(f"Loaded Silero VAD model (threshold={threshold})")
        except NameError:
            raise ImportError("Please install silero-vad first: pip install silero-vad")

    def contains_speech(self, audio: np.ndarray) -> bool:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        audio_tensor = torch.from_numpy(audio)
        
        try:
            timestamps = get_speech_timestamps(
                audio_tensor, 
                self.model, 
                threshold=self.threshold,
                sampling_rate=self.sample_rate,
                min_speech_duration_ms=50,
                return_seconds=False
            )
            return len(timestamps) > 0
        except Exception as e:
            logger.error(f"VAD Error: {e}")
            return False

    def change_threshold(self, threshold: float):
        self.threshold = threshold


class VoiceActivityDetectorStreaming:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        if sample_rate not in (8000, 16000):
            raise ValueError("Silero VAD supports only 8000 or 16000 Hz")
        try:
            self.model = load_silero_vad(onnx=True)
        except NameError:
            raise ImportError("Please install silero-vad first: pip install silero-vad")

        self.threshold = threshold
        self.sample_rate = sample_rate
        self.window_size = 512 if sample_rate == 16000 else 256
        self.internal_buffer = np.empty(0, dtype=np.float32)
        self.vad_iterator = VADIterator(
            self.model,
            threshold=threshold,
            sampling_rate=sample_rate,
        )
        logger.info(
            "Loaded streaming Silero VAD (threshold=%.2f, sr=%d, window=%d)",
            threshold, sample_rate, self.window_size,
        )

    def contains_speech(self, audio: np.ndarray) -> bool:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Accumulate, then run the model on each full window in order; the
        # remainder (<window_size) stays buffered for the next call.
        self.internal_buffer = np.concatenate([self.internal_buffer, audio.reshape(-1)])
        try:
            while self.internal_buffer.size >= self.window_size:
                window = self.internal_buffer[: self.window_size]
                self.internal_buffer = self.internal_buffer[self.window_size :]
                self.vad_iterator(torch.from_numpy(window))
        except Exception as e:
            logger.error(f"VAD Error: {e}")
            return False

        return self.vad_iterator.triggered

    def change_threshold(self, threshold: float):
        self.threshold = threshold
        self.vad_iterator.threshold = threshold

    def reset(self):
        """Clear streaming state. Call between utterances / on barge-in."""
        self.vad_iterator.reset_states()
        self.internal_buffer = np.empty(0, dtype=np.float32)
        
        
