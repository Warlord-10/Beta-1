from __future__ import annotations

import queue
import threading
import time
from queue import Queue
from typing import Callable, Iterator, Optional

import numpy as np
import sounddevice as sd

from src.asr.aec import aec
from src.config.global_events import *
from src.config.global_queues import LLMChunkQueue
from src.config.logger import get_logger
from src.observability import Metric, Stopwatch, latency_tracker
from src.utils.text_utils import clean_text
from src.voice.factory import get_tts_engine
from src.config.settings import SETTINGS

logger = get_logger("tts.service")

# Sentinel for clean shutdown
_SHUTDOWN = object()

class TTSService:
    def __init__(self):
        # MLX binds work to the thread-local GPU stream of whichever thread
        # constructs the model. Building the TTS engine on the main thread but
        # generating from the tts-worker thread raises "There is no
        # Stream(gpu, 0) in current thread". Defer construction to stream()
        # (runs on the worker thread) so load + warmup + execute share a stream.
        self._tts_config = SETTINGS.TTS_CONFIG
        self.tts = None
        self.provider = SETTINGS.TTS_CONFIG.get("provider", "tts")
        self.sample_rate = SETTINGS.TTS_SAMPLE_RATE
        self._leftover = np.array([], dtype="float32")
        self.AudioChunkQueue = Queue()


    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("Audio status: %s", status)

        needed = frames
        result = self._leftover

        # Drain audio_queue without blocking — pad with silence if needed
        while len(result) < needed:
            try:
                chunk = self.AudioChunkQueue.get_nowait()
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
        flushed = 0
        while not self.AudioChunkQueue.empty():
            try:
                self.AudioChunkQueue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        if flushed:
            logger.debug("Flushed %d audio chunks on barge-in", flushed)
        self._leftover = np.array([], dtype="float32")
        aec.reset_reference()

    def generate_audio(self, text: str) -> None:
        if not text.strip():
            return

        stopwatch = Stopwatch()
        first_chunk_seen = False

        for audio_chunk in self.tts.synthesize(text):
            if CheckUserBargeIn():
                self._flush_audio_queue()
                return

            # Normalise to a 1-D float32 array — synthesize() may yield a torch
            # tensor, or a scalar/0-D array for tiny segments, which would crash
            # np.concatenate in the audio callback.
            chunk = np.asarray(audio_chunk, dtype="float32").reshape(-1)
            if chunk.size == 0:
                continue

            if not first_chunk_seen:
                first_chunk_seen = True
                latency_tracker.record(
                    Metric.TTS_FIRST_AUDIO, stopwatch.elapsed_ms(), provider=self.provider
                )

            self.AudioChunkQueue.put(chunk)

        latency_tracker.record(
            Metric.TTS_SYNTHESIZE, stopwatch.elapsed_ms(), provider=self.provider
        )

    def _ensure_tts(self) -> None:
        """Lazily build the MLX TTS engine on the calling (worker) thread."""
        if self.tts is None:
            self.tts = get_tts_engine(config=self._tts_config)

    def stream(self):
        self._ensure_tts()
        while True:
            is_tts_enabled_event.wait()
            
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.sample_rate//100,  # 10 ms @ 24 kHz — one AEC reference frame per callback
                callback=self._callback,
                latency="high",
            ):
                while IsTTSEnabled():
                    # Barge-in: user started speaking mid-playback
                    if CheckUserBargeIn():
                        self._flush_audio_queue()
                        time.sleep(0.05)
                        continue

                    try:
                        llm_chunk = LLMChunkQueue.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    # Shutdown sentinel
                    if llm_chunk is None:
                        logger.info("TTS received shutdown sentinel")
                        self.AudioChunkQueue.put(_SHUTDOWN)
                        break

                    logger.debug(f"TTS received chunk: {llm_chunk[:40]}")
                    self.generate_audio(llm_chunk)

    def shutdown(self) -> None:
        LLMChunkQueue.put(None)