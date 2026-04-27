
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Iterator, Optional

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
from src.voice.base import BaseTTS

logger = get_logger("voice.kokoro")

# Sentinel for clean shutdown
_SHUTDOWN = object()


class KokoroTTS(BaseTTS):
    """
    Kokoro TTS integration.

    Responsibilities:
      - synthesize()  : text  ──► numpy audio chunks (generator)
      - stream()      : pulls from llm_chunk_queue, feeds audio_queue
      - _callback()   : sounddevice callback, drains audio_queue into DAC
    """

    def __init__(
        self,
        voice_name: str = "af_heart",
        sample_rate: int = 24000,
        speed: float = 1.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.voice_name = voice_name
        self.speed = speed

        # Injected via attach() — not owned by TTS
        self._llm_chunk_queue: Optional[queue.Queue] = None
        self._is_user_speaking: Optional[threading.Event] = None

        # Internal audio pipeline
        self._audio_queue: queue.Queue = queue.Queue(maxsize=20)
        self._leftover = np.array([], dtype="float32")

        lang_code = voice_name[0] if voice_name else "a"
        logger.info("Initializing Kokoro TTS (lang=%s, voice=%s)", lang_code, voice_name)
        self.pipeline = KPipeline(lang_code=lang_code)
        logger.info("Kokoro TTS ready")

    def attach(
        self,
        llm_chunk_queue: queue.Queue,
        is_user_speaking: threading.Event,
    ) -> None:
        """Inject runtime dependencies. Call before stream()."""
        self._llm_chunk_queue = llm_chunk_queue
        self._is_user_speaking = is_user_speaking

    
    def _check_user_speaking(self) -> bool:
        if self._is_user_speaking and self._is_user_speaking.is_set():
            return True
        return False


    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("Audio status: %s", status)

        needed = frames
        result = self._leftover

        # Drain audio_queue without blocking — pad with silence if needed
        while len(result) < needed:
            try:
                chunk = self._audio_queue.get_nowait()
                if chunk is _SHUTDOWN:
                    break
                result = np.concatenate([result, chunk])
            except queue.Empty:
                break  # not enough audio ready — will pad below

        if len(result) >= needed:
            outdata[:] = result[:needed].reshape(-1, 1)
            self._leftover = result[needed:]
        else:
            # Pad with silence — avoids underrun noise
            outdata[: len(result)] = result.reshape(-1, 1)
            outdata[len(result) :] = 0
            self._leftover = np.array([], dtype="float32")


    def synthesize(self, text: str) -> Iterator[np.ndarray]:
        """
        Yields numpy audio chunks for the given text.
        This is a generator — iterate it, don't call it like a function.
        """
        text = clean_text(text)
        if not text.strip():
            return

        try:
            logger.debug("Synthesizing: %r", text[:60])
            for _gs, _ps, audio in self.pipeline(
                text,
                voice=self.voice_name,
                speed=self.speed,
                split_pattern=r"\n+",
            ):
                yield audio
        except Exception:
            logger.exception("Kokoro synthesis failed for: %r", text[:60])


    def _flush_audio_queue(self) -> None:
        """Discard buffered audio when user starts speaking (barge-in)."""
        flushed = 0
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        if flushed:
            logger.debug("Flushed %d audio chunks on barge-in", flushed)
        self._leftover = np.array([], dtype="float32")

    def stream(self) -> None:
        """
        Thread entry-point.
        Pulls sentences from llm_chunk_queue ──► synthesizes ──► audio_queue.
        """
        assert self._llm_chunk_queue is not None, "Call attach() before stream()"

        with sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        ):
            while True:
                # Barge-in: user started speaking mid-playback
                if self._check_user_speaking():
                    self._flush_audio_queue()
                    time.sleep(0.05)
                    continue

                try:
                    llm_chunk = self._llm_chunk_queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                # Shutdown sentinel
                if llm_chunk is None:
                    logger.info("TTS received shutdown sentinel")
                    self._audio_queue.put(_SHUTDOWN)
                    break

                logger.debug("TTS received chunk: %r", llm_chunk[:40])
                for audio_chunk in self.synthesize(llm_chunk):
                    # Check barge-in during synthesis too
                    if self._check_user_speaking():
                        logger.debug("Barge-in during synthesis — discarding")
                        break
                    self._audio_queue.put(audio_chunk)  # blocks if full → backpressure

    def shutdown(self) -> None:
        if self._llm_chunk_queue:
            self._llm_chunk_queue.put(None)

    def play(self):
        pass