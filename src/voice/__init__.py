"""Voice Module — Interfaces for STT and TTS engines."""

from src.voice.base import BaseTTS
from src.voice.factory import get_tts_engine

__all__ = ["BaseTTS", "get_tts_engine"]

