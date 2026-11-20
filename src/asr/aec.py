"""Acoustic echo cancellation (AEC) for the mic.

The speaker callback hands every block it plays to ``push_speaker``. A worker
thread resamples those blocks to the mic rate and feeds them to the WebRTC
audio processor as the echo reference. ``process_mic`` then removes that echo
from each 10 ms mic frame (plus noise suppression and auto gain).

While the speaker is quiet there is no echo to remove, so mic frames skip the
processor entirely. That is most of the idle CPU this module used to burn.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time

import numpy as np
import soxr
from aec_audio_processing import AudioProcessor

from src.config.settings import SETTINGS

SAMPLE_RATE = SETTINGS.MIC_SAMPLE_RATE   # the processor runs at the mic rate
SPEAKER_SAMPLE_RATE = SETTINGS.TTS_SAMPLE_RATE
FRAME_SAMPLES = SAMPLE_RATE // 100       # the processor works on 10 ms frames

# Delay between a sample being handed to the speaker and its echo reaching the
# mic. With sounddevice latency="high" on macOS this is typically 150-250 ms.
STREAM_DELAY_MS = 200

# How long after the last speaker block an echo can still arrive:
# output buffer + STREAM_DELAY_MS + room reverb.
# ponytail: fixed guess; raise it if the bot's last word triggers a barge-in.
ECHO_TAIL_S = 0.5

_RESET = object()   # queue marker: start the reference over (barge-in)


def _to_int16_bytes(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def _to_float32(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def _new_processor() -> AudioProcessor:
    processor = AudioProcessor(enable_aec=True, enable_ns=True, enable_agc=True, enable_vad=False)
    processor.set_stream_format(
        sample_rate_in=SAMPLE_RATE,
        channel_count_in=1,
        sample_rate_out=SAMPLE_RATE,
        channel_count_out=1,
    )
    processor.set_reverse_stream_format(SAMPLE_RATE, 1)
    processor.set_stream_delay(STREAM_DELAY_MS)
    return processor


def _new_resampler() -> soxr.ResampleStream:
    """Speaker rate → mic rate, keeping state between blocks for gapless output."""
    return soxr.ResampleStream(SPEAKER_SAMPLE_RATE, SAMPLE_RATE, num_channels=1, dtype=np.float32)


class AcousticEchoCanceller:
    def __init__(self):
        self._processor = _new_processor()
        self._lock = threading.Lock()   # the mic and the worker both use the processor
        self._speaker_blocks: queue.Queue = queue.Queue(maxsize=64)
        self._last_played = 0.0         # time.monotonic() of the latest speaker block
        threading.Thread(target=self._reference_worker, name="aec-reverse", daemon=True).start()

    # ---- mic side ---------------------------------------------------------

    def process_mic(self, frame: np.ndarray) -> np.ndarray:
        """One 10 ms float32 mic frame in, the same frame with the bot's echo removed out."""
        if not self._speaker_recently_played() or len(frame) != FRAME_SAMPLES:
            return frame
        with self._lock:
            cleaned = self._processor.process_stream(_to_int16_bytes(frame))
        return _to_float32(cleaned)

    def _speaker_recently_played(self) -> bool:
        return time.monotonic() - self._last_played < ECHO_TAIL_S

    # ---- speaker side -----------------------------------------------------

    def push_speaker(self, block: np.ndarray) -> None:
        """Hand over a block the speaker is playing.

        Safe to call from the audio callback: it only records the time and
        queues the block; the DSP runs on the worker thread.
        """
        self._last_played = time.monotonic()
        self._put(block)

    def reset_reference(self) -> None:
        """Forget the queued speaker audio (call on barge-in)."""
        while True:
            try:
                self._speaker_blocks.get_nowait()
            except queue.Empty:
                break
        self._put(_RESET)

    def _put(self, item) -> None:
        try:
            self._speaker_blocks.put_nowait(item)
        except queue.Full:
            # The worker fell behind: drop the oldest block so the reference stays current.
            with contextlib.suppress(queue.Empty):
                self._speaker_blocks.get_nowait()
            with contextlib.suppress(queue.Full):
                self._speaker_blocks.put_nowait(item)

    def _reference_worker(self) -> None:
        """Resample played audio to the mic rate and feed it to the processor in 10 ms frames."""
        resampler = _new_resampler()
        pending = np.empty(0, dtype=np.float32)   # resampled audio not yet a full frame

        while True:
            block = self._speaker_blocks.get()
            if block is _RESET:
                resampler = _new_resampler()
                pending = pending[:0]
                continue

            resampled = resampler.resample_chunk(np.asarray(block, dtype=np.float32))
            pending = np.concatenate([pending, resampled])
            usable = len(pending) - len(pending) % FRAME_SAMPLES
            if not usable:
                continue

            frames = [_to_int16_bytes(f) for f in pending[:usable].reshape(-1, FRAME_SAMPLES)]
            pending = pending[usable:]
            with self._lock:
                for frame in frames:
                    self._processor.process_reverse_stream(frame)


aec = AcousticEchoCanceller()
