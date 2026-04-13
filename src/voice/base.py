"""Base interface for TTS Engines."""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class BaseTTS(ABC):
    """Abstract base class summarizing operations required for Beta-1 Voice."""

    @abstractmethod
    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """Synthesize text into a raw numpy array.
        
        Args:
            text: Text to synthesize.

        Returns:
            A corresponding numpy array representing the audio wave, or None if failed.
        """
        pass

    @abstractmethod
    def play(self, text: str, block: bool = True) -> None:
        """Synthesize and play the audio through system speakers.
        
        Args:
            text: The text string to synthesize and play.
            block: If True, blocks until playback finishes.
        """
        pass

    @abstractmethod
    def save(self, text: str, file_path: str) -> None:
        """Synthesize and directly save audio to a WAV file."""
        pass
