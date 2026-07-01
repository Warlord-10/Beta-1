"""Base interface for TTS Engines."""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class BaseTTS(ABC):
    """Abstract base class summarizing operations required for Beta-1 Voice."""

    @abstractmethod
    def synthesize(self, text: str) -> Optional[np.ndarray]:
        pass
    
    @abstractmethod
    def _warmup(self) -> None:
        pass
