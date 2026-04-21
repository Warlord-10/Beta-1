"""Base interface for ASR (Speech-to-Text) Engines."""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class BaseASR(ABC):
    """Abstract base class summarizing operations required for Beta-1 ASR."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe an audio numpy array into text.
        
        Args:
            audio: A 1D numpy array of audio samples (typically floating point -1.0 to 1.0).
            sample_rate: The sample rate of the audio array (default 16000).

        Returns:
            The transcribed text string.
        """
        pass
