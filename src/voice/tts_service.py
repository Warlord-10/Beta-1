"""Text-to-speech playback.

Two pieces work together:

- **TTS worker** (``stream``, its own thread): sleeps on ``LLMChunkQueue``.
  For each text chunk it synthesises audio, queues it, and starts the
  speaker stream if it is stopped.
- **Speaker callback** (``_callback``, called by the sound card every 10 ms
  while the stream runs): plays the queued audio, hands each block to the
  echo canceller, and stops the stream once everything has played.

So while the bot is quiet, nothing runs on the speaker side.
"""

from __future__ import annotations

import queue
import time

import numpy as np
import sounddevice as sd

from src.asr.aec import aec
from src.config.global_events import CheckUserBargeIn, IsTTSEnabled
from src.config.global_queues import LLMChunkQueue
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.observability import Metric, Stopwatch, latency_tracker
from src.voice.factory import get_tts_engine

logger = get_logger("tts.service")

# Audio buffered before playback starts. Without it, a synth that lags
# for a moment leaves half-empty blocks, heard as clicks.
# Raise it if synthesis is slower than real time on your machine.
_PREBUFFER_S = 0.1
# Silence kept before the first and after the last voiced sample of each
# chunk. Kokoro pads chunks with ~300 ms lead / ~370 ms tail, which made
# ~0.7 s of dead air between sentences.
_KEEP_SILENCE_S = 0.1
# |sample| above this counts as voice.
_SILENCE_LEVEL = 0.01
_BARGE_IN_POLL_S = 0.05


class TTSService:
    def __init__(self):
        # MLX ties a model to the thread that builds it, so the engine is
        # built in stream(), on the worker thread that also uses it.
        self._tts_config = SETTINGS.TTS_CONFIG
        self.provider = self._tts_config.get("provider", "tts")
        self.tts = None
        self.sample_rate = SETTINGS.TTS_SAMPLE_RATE
        self._prebuffer = int(self.sample_rate * _PREBUFFER_S)
        self._stream: sd.OutputStream | None = None

        # Worker → callback.
        self._audio: queue.Queue[np.ndarray] = queue.Queue()
        # Callback-only playback state.
        self._buffer = np.empty(0, dtype=np.float32)   # taken from the queue, not yet played
        self._playing = False        # False → wait for a full prebuffer first
        # Flags shared by the worker and the callback.
        self._idle = True            # the stream is stopped
        self._synthesizing = False   # the worker may still queue audio

    # ---- TTS worker ---------------------------------------------------------

    def stream(self) -> None:
        """TTS worker loop: speak every text chunk the LLM sends."""
        self.tts = self.tts or get_tts_engine(config=self._tts_config)
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.sample_rate // 100,   # 10 ms: one echo-reference block per callback
            latency="high",
            callback=self._callback,
        )
        try:
            while (text := LLMChunkQueue.get()) is not None:   # sleeps until text arrives
                self._wait_out_barge_in()
                if not IsTTSEnabled():
                    continue
                self._synthesizing = True
                try:
                    self.generate_audio(text)
                finally:
                    self._synthesizing = False
        finally:
            self._stream.close()
            logger.info("TTS worker stopped")

    def shutdown(self) -> None:
        LLMChunkQueue.put(None)

    @staticmethod
    def _wait_out_barge_in() -> None:
        """Hold the rest of the reply while the user talks over the bot."""
        # ponytail: polls, but only while the user is speaking.
        while CheckUserBargeIn():
            time.sleep(_BARGE_IN_POLL_S)

    def generate_audio(self, text: str) -> None:
        """Synthesise text and queue it for the speaker, trimming dead air."""
        if not text.strip():
            return
        logger.debug("TTS received chunk: %s", text[:40])

        stopwatch = Stopwatch()
        keep = int(self.sample_rate * _KEEP_SILENCE_S)
        samples = 0
        # Trailing silence of the audio so far. Held back instead of played:
        # if more voice follows it was a real pause and gets played, otherwise
        # only `keep` of it is played at the end. Voiced audio is never held,
        # so the time to first audio is unchanged.
        held = np.empty(0, dtype=np.float32)

        def emit(audio: np.ndarray) -> None:
            nonlocal samples
            if audio.size == 0:
                return
            if samples == 0:
                latency_tracker.record(
                    Metric.TTS_FIRST_AUDIO, stopwatch.elapsed_ms(),
                    provider=self.provider, chars=len(text),
                )
            samples += audio.size
            self._play(audio)

        for chunk in self.tts.synthesize(text):
            if CheckUserBargeIn() or not IsTTSEnabled():
                return   # the callback discards what is already queued
            # Providers may yield tensors or 0-D arrays: make it a flat float32 array.
            chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
            voiced = np.flatnonzero(np.abs(chunk) > _SILENCE_LEVEL)
            if voiced.size == 0:
                if samples:
                    held = np.concatenate([held, chunk])
                continue   # silence before the first voice is dropped

            if samples:
                emit(held)                       # the held silence was a pause in speech
                start = 0
            else:
                start = max(0, voiced[0] - keep)   # trim leading silence
            end = voiced[-1] + 1
            emit(chunk[start:end])
            held = chunk[end:]

        emit(held[:keep])   # trim trailing silence
        self._record_synthesis(text, samples, stopwatch.elapsed_ms())

    def _record_synthesis(self, text: str, samples: int, elapsed_ms: float) -> None:
        # rtf < 1: synthesis outruns playback. rtf >= 1: audible gaps.
        audio_ms = samples / self.sample_rate * 1000.0
        latency_tracker.record(
            Metric.TTS_SYNTHESIZE, elapsed_ms,
            provider=self.provider,
            chars=len(text),
            audio_ms=round(audio_ms),
            rtf=round(elapsed_ms / audio_ms, 2) if audio_ms else None,
        )

    def _play(self, audio: np.ndarray) -> None:
        """Queue audio for the speaker and start the stream if it is stopped."""
        self._audio.put(audio)
        if self._idle:
            self._idle = False
            # ponytail: if the callback un-idles itself at this exact moment,
            # this restarts a running stream: a brief gap, no lost audio.
            self._stream.stop()   # no-op if already stopped
            self._stream.start()

    # ---- speaker callback ---------------------------------------------------

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """The sound card wants the next 10 ms. Runs only while the stream is started."""
        if status:
            logger.warning("Audio status: %s", status)
        out = outdata[:, 0]
        out.fill(0)

        if CheckUserBargeIn() or not IsTTSEnabled():
            self._discard_audio()
        else:
            self._fill(out)
        aec.push_speaker(out.copy())

        if self._finished():
            self._playing = False
            raise sd.CallbackStop   # plays out the device buffer, then stops

    def _fill(self, out: np.ndarray) -> None:
        """Copy the next block of queued audio into ``out`` (already silent)."""
        target = len(out) if self._playing else self._prebuffer
        while len(self._buffer) < target:
            try:
                chunk = self._audio.get_nowait()
            except queue.Empty:
                break
            self._buffer = np.concatenate([self._buffer, chunk])

        if len(self._buffer) < target and self._synthesizing:
            # Synthesis is behind: play silence and keep what we have, so
            # speech resumes in one piece instead of being cut mid-waveform.
            self._playing = False
            return

        n = min(len(out), len(self._buffer))
        out[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        self._playing = True

    def _finished(self) -> bool:
        """True once everything queued has been played.

        ``_idle`` is set before the last look at the queue, so audio the
        worker queues at this exact moment is either seen here, or the worker
        sees ``_idle`` and restarts the stream. It can't get stuck in between.
        """
        if len(self._buffer):
            return False
        self._idle = True
        if self._audio.empty():
            return True
        self._idle = False
        return False

    def _discard_audio(self) -> None:
        """Drop everything not yet played (barge-in, or TTS turned off)."""
        dropped = len(self._buffer)
        while True:
            try:
                dropped += len(self._audio.get_nowait())
            except queue.Empty:
                break
        if dropped:   # once per barge-in: the next calls find nothing left
            logger.info("Speech cut off (barge-in or TTS off): dropped %.1fs of audio", dropped / self.sample_rate)
        self._buffer = self._buffer[:0]
        aec.reset_reference()
