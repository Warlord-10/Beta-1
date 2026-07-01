"""Base interface for ASR (Speech-to-Text) Engines."""

from abc import ABC, abstractmethod
from typing import Optional
from src.config.settings import SETTINGS
import numpy as np


class BaseASR(ABC):
    """Abstract base class summarizing operations required for Beta-1 ASR."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = SETTINGS.STT_SAMPLE_RATE) -> str:
        pass
