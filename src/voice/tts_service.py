from __future__ import annotations

import queue
import time
from queue import Queue

import numpy as np
import sounddevice as sd

from src.asr.aec import aec
from src.config.global_events import *
from src.config.global_queues import LLMChunkQueue
from src.config.logger import get_logger
from src.observability import Metric, Stopwatch, latency_tracker
from src.voice.factory import get_tts_engine
from src.config.settings import SETTINGS

logger = get_logger("tts.service")

# Sentinel for clean shutdown
_SHUTDOWN = object()

# Silence kept before the first and after the last voiced sample of each TTS
# chunk. Kokoro pads every chunk with ~300 ms lead / ~370 ms tail, which made
# ~0.7 s of dead air between sentences.
_KEEP_SILENCE_S = 0.1
# |sample| above this counts as voice.
_SILENCE_LEVEL = 0.01

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
        # ponytail: 100 ms jitter buffer. Without it the callback emitted
        # half-filled blocks padded with zeros whenever synthesis lagged, and the
        # mid-waveform cut is what you hear as static/clicks. Raise if the synth
        # is slower than realtime on your box.
        self._prebuffer = int(self.sample_rate * 0.1)
        self._playing = False


    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("Audio status: %s", status)

        needed = frames
        result = self._leftover
        target = needed if self._playing else max(needed, self._prebuffer)

        # Drain audio_queue without blocking
        while len(result) < target:
            try:
                chunk = self.AudioChunkQueue.get_nowait()
                if chunk is _SHUTDOWN:
                    break

                result = np.concatenate([result, chunk])
            except queue.Empty:
                break

        if len(result) >= target:
            self._playing = True
            outdata[:] = result[:needed].reshape(-1, 1)
            self._leftover = result[needed:]
        else:
            # Underrun: emit a full block of silence and keep every sample we
            # have, so playback resumes contiguously instead of being cut
            # mid-waveform. Re-arms the prebuffer for the next start.
            outdata[:] = 0
            self._leftover = result
            self._playing = False

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
        self._playing = False
        aec.reset_reference()

    def generate_audio(self, text: str) -> None:
        if not text.strip():
            return

        stopwatch = Stopwatch()
        first_chunk_seen = False
        samples = 0
        keep = int(self.sample_rate * _KEEP_SILENCE_S)
        # Trailing silence of the audio so far. Held back instead of played: if
        # more voice follows it's a real pause and gets played, otherwise only
        # `keep` of it is played at the end. Voiced audio is never delayed, so
        # streaming providers keep their time-to-first-audio.
        held = np.array([], dtype="float32")

        def play(audio: np.ndarray) -> None:
            nonlocal first_chunk_seen, samples
            if audio.size == 0:
                return
            if not first_chunk_seen:
                first_chunk_seen = True
                latency_tracker.record(
                    Metric.TTS_FIRST_AUDIO,
                    stopwatch.elapsed_ms(),
                    provider=self.provider,
                    chars=len(text),
                )
            samples += audio.size
            self.AudioChunkQueue.put(audio)

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

            voiced = np.flatnonzero(np.abs(chunk) > _SILENCE_LEVEL)
            if voiced.size == 0:
                if first_chunk_seen:
                    held = np.concatenate([held, chunk])
                continue  # silence before any voice is dropped

            start = 0
            if not first_chunk_seen:
                start = max(0, voiced[0] - keep)  # trim leading silence
            else:
                play(held)  # the held silence was a pause inside speech
            end = voiced[-1] + 1
            play(chunk[start:end])
            held = chunk[end:]

        play(held[:keep])  # trim trailing silence

        # rtf < 1 means synthesis outruns playback (queue stays fed); >= 1 means
        # the speaker drains faster than we can fill it, i.e. audible gaps.
        elapsed = stopwatch.elapsed_ms()
        audio_ms = samples / self.sample_rate * 1000.0
        latency_tracker.record(
            Metric.TTS_SYNTHESIZE,
            elapsed,
            provider=self.provider,
            chars=len(text),
            audio_ms=round(audio_ms),
            rtf=round(elapsed / audio_ms, 2) if audio_ms else None,
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