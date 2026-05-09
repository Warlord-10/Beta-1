
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
from src.config.events import GlobalEvents, GlobalQueues
from src.asr.aec import aec

logger = get_logger("voice.kokoro")

# Sentinel for clean shutdown
_SHUTDOWN = object()


class KokoroTTS(BaseTTS):

    def __init__(
        self,
        voice_name: str = "af_heart",
        sample_rate: int = 24000,
        speed: float = 1.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.voice_name = voice_name
        self.speed = speed

        # Internal audio pipeline
        self._leftover = np.array([], dtype="float32")

        lang_code = voice_name[0] if voice_name else "a"
        logger.info("Initializing Kokoro TTS (lang=%s, voice=%s)", lang_code, voice_name)
        self.pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        self._warmup()
        logger.info("Kokoro TTS ready")

    def _warmup(self) -> None:
        """Force voice tensor load + first-call graph build at startup."""
        try:
            for _ in self.pipeline(
                "warmup.",
                voice=self.voice_name,
                speed=self.speed,
                split_pattern=r"\n+",
            ):
                pass
        except Exception:
            logger.exception("Kokoro warmup failed")

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("Audio status: %s", status)

        needed = frames
        result = self._leftover

        # Drain audio_queue without blocking — pad with silence if needed
        while len(result) < needed:
            try:
                chunk = GlobalQueues.audio_chunk_queue.get_nowait()
                if chunk is _SHUTDOWN:
                    break
                result = np.concatenate([result, chunk])
            except queue.Empty:
                break

        if len(result) >= needed:
            outdata[:] = result[:needed].reshape(-1, 1)
            self._leftover = result[needed:]
        else:
            # Pad with silence — avoids underrun noise
            outdata[: len(result)] = result.reshape(-1, 1)
            outdata[len(result) :] = 0
            self._leftover = np.array([], dtype="float32")

        chunk_for_aec = outdata[:, 0].copy()
        aec.push_speaker(chunk_for_aec)

    def _flush_audio_queue(self) -> None:
        """Discard buffered audio when user starts speaking (barge-in)."""
        flushed = 0
        while not GlobalQueues.audio_chunk_queue.empty():
            try:
                GlobalQueues.audio_chunk_queue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        if flushed:
            logger.debug("Flushed %d audio chunks on barge-in", flushed)
        self._leftover = np.array([], dtype="float32")
        aec.reset_reference()

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
                split_pattern=r'\n+',
            ):
                # Check barge-in while streaming audio
                if GlobalEvents.is_user_speaking():
                    self._flush_audio_queue()
                    return

                GlobalQueues.audio_chunk_queue.put(audio)

        except Exception:
            logger.exception("Kokoro synthesis failed for: %r", text[:60])

    def stream(self) -> None:
        """
        Thread entry-point.
        Pulls sentences from llm_chunk_queue ──► synthesizes ──► audio_queue.
        """
        while True:
            GlobalEvents.is_tts_enabled_event.wait()
            
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=240,  # 10 ms @ 24 kHz — one AEC reference frame per callback
                callback=self._callback,
                latency="high",
            ):
                while GlobalEvents.is_tts_enabled():
                    # Barge-in: user started speaking mid-playback
                    if GlobalEvents.is_user_speaking():
                        self._flush_audio_queue()
                        time.sleep(0.05)
                        continue

                    try:
                        llm_chunk = GlobalQueues.llm_chunk_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    # Shutdown sentinel
                    if llm_chunk is None:
                        logger.info("TTS received shutdown sentinel")
                        GlobalQueues.audio_chunk_queue.put(_SHUTDOWN)
                        break

                    logger.debug("TTS received chunk: %r", llm_chunk[:40])
                    self.synthesize(llm_chunk)

    def shutdown(self) -> None:
        GlobalQueues.llm_chunk_queue.put(None)

    def play(self):
        pass