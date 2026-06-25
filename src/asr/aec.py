"""Acoustic Echo Cancellation (AEC) module.

Uses the WebRTC APM via `aec_audio_processing` for echo cancellation, noise
suppression, and automatic gain control.  Optimised for real-time streaming:

  • soxr (libsoxr) replaces scipy.resample_poly — 3-5× faster C resampler.
  • A pre-allocated ring-buffer replaces np.concatenate — O(1) frame writes
    instead of O(n) copies every 10 ms.
  • Conversion helpers use pre-allocated scratch buffers where possible.
  • The reverse-stream worker batches all pending frames before acquiring the
    lock, reducing contention on the hot mic-processing path.
"""

from __future__ import annotations

import queue
import threading

import numpy as np
import soxr
from aec_audio_processing import AudioProcessor
from src.config.settings import SETTINGS

# WebRTC APM only supports 8/16/32/48 kHz. Speaker stream is resampled 24k → 16k internally.
MIC_SAMPLE_RATE = SETTINGS.MIC_SAMPLE_RATE
SPEAKER_SAMPLE_RATE = SETTINGS.TTS_SAMPLE_RATE
APM_SAMPLE_RATE = MIC_SAMPLE_RATE
FRAME_MS = 10
MIC_FRAME_SAMPLES = MIC_SAMPLE_RATE * FRAME_MS // 1000      # 160
APM_FRAME_SAMPLES = APM_SAMPLE_RATE * FRAME_MS // 1000      # 160
SPEAKER_FRAME_SAMPLES = SPEAKER_SAMPLE_RATE * FRAME_MS // 1000  # 240

# Round-trip delay between a sample fed to process_reverse_stream and the same
# echo arriving at process_stream. With sounddevice latency="high" on macOS this
# is typically 150-250 ms.
STREAM_DELAY_MS = 200

# ---------------------------------------------------------------------------
# Pre-allocated scratch buffers — avoids per-frame heap allocations.
# ---------------------------------------------------------------------------
_MIC_SCRATCH_I16 = np.empty(MIC_FRAME_SAMPLES, dtype=np.int16)
_REV_SCRATCH_I16 = np.empty(APM_FRAME_SAMPLES, dtype=np.int16)

# Ring-buffer capacity (in samples).  ~100 ms of 16 kHz audio — more than
# enough to absorb scheduling jitter between the speaker callback and the
# reverse-stream worker without ever calling np.concatenate.
_RING_CAPACITY = APM_FRAME_SAMPLES * 16  # 2560 samples


def _f32_to_int16_bytes(x: np.ndarray, scratch: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] → int16 bytes, reusing *scratch* to avoid alloc."""
    np.multiply(x, 32768.0, out=scratch, casting="unsafe")
    np.clip(scratch, -32768, 32767, out=scratch)
    return scratch.tobytes()


def _int16_bytes_to_f32(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.int16).astype(np.float32, copy=False) * (1.0 / 32768.0)


# ---------------------------------------------------------------------------
# Ring-buffer for the speaker reference stream.
# ---------------------------------------------------------------------------
class _RingBuffer:
    """Fixed-capacity ring-buffer for float32 audio samples.

    All operations are O(1) amortised (no np.concatenate).  The buffer
    silently drops the oldest samples when it overflows so that the
    reference signal never drifts arbitrarily far behind.
    """

    __slots__ = ("_buf", "_cap", "_write", "_readable")

    def __init__(self, capacity: int) -> None:
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._cap = capacity
        self._write = 0      # next write position (mod capacity)
        self._readable = 0   # number of unread samples

    def write(self, data: np.ndarray) -> None:
        n = data.shape[0]
        if n == 0:
            return
        if n >= self._cap:
            # More data than the whole buffer — keep only the tail.
            data = data[-self._cap:]
            n = self._cap
            self._buf[:] = data
            self._write = 0
            self._readable = self._cap
            return
        end = self._write + n
        if end <= self._cap:
            self._buf[self._write:end] = data
        else:
            first = self._cap - self._write
            self._buf[self._write:] = data[:first]
            self._buf[:n - first] = data[first:]
        self._write = end % self._cap
        self._readable = min(self._readable + n, self._cap)

    def read(self, n: int) -> np.ndarray | None:
        """Return exactly *n* samples or None if not enough data."""
        if self._readable < n:
            return None
        start = (self._write - self._readable) % self._cap
        end = start + n
        if end <= self._cap:
            out = self._buf[start:end].copy()
        else:
            out = np.empty(n, dtype=np.float32)
            first = self._cap - start
            out[:first] = self._buf[start:]
            out[first:] = self._buf[:n - first]
        self._readable -= n
        return out

    def clear(self) -> None:
        self._readable = 0
        self._write = 0


class AcousticEchoCanceller:
    def __init__(self):
        self._ap = AudioProcessor(
            enable_aec=True,
            enable_ns=True,
            enable_agc=True,
            enable_vad=False,
        )
        self._ap.set_stream_format(
            sample_rate_in=MIC_SAMPLE_RATE,
            channel_count_in=1,
            sample_rate_out=MIC_SAMPLE_RATE,
            channel_count_out=1,
        )
        self._ap.set_reverse_stream_format(APM_SAMPLE_RATE, 1)
        self._ap.set_stream_delay(STREAM_DELAY_MS)

        # Persistent soxr resampler — keeps state across calls for gapless
        # resampling without boundary artefacts.
        self._resampler = soxr.ResampleStream(
            SPEAKER_SAMPLE_RATE,
            APM_SAMPLE_RATE,
            num_channels=1,
            dtype=np.float32,
        )

        self._apm_lock = threading.Lock()
        self._speaker_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=64)
        self._ring = _RingBuffer(_RING_CAPACITY)
        self._worker = threading.Thread(
            target=self._reverse_worker, name="aec-reverse", daemon=True
        )
        self._worker.start()

    def process_mic(self, chunk: np.ndarray) -> np.ndarray:
        """One 10 ms float32 mic frame (160 samples @ 16 kHz) in, cleaned frame out."""
        if chunk.shape[0] != MIC_FRAME_SAMPLES:
            return chunk
        if chunk.dtype != np.float32:
            chunk = chunk.astype(np.float32)
        with self._apm_lock:
            cleaned = self._ap.process_stream(
                _f32_to_int16_bytes(chunk, _MIC_SCRATCH_I16)
            )
        return _int16_bytes_to_f32(cleaned)

    def push_speaker(self, chunk: np.ndarray) -> None:
        """Fire-and-forget: enqueue a 24 kHz float32 speaker block.

        Safe to call from a sounddevice output callback — no DSP runs here.
        """
        try:
            self._speaker_q.put_nowait(chunk)
        except queue.Full:
            # Worker is behind. Drop the oldest frame to keep alignment current
            # rather than letting the reference signal lag arbitrarily.
            try:
                self._speaker_q.get_nowait()
                self._speaker_q.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                pass

    def reset_reference(self) -> None:
        """Drop pending speaker audio (call on barge-in)."""
        while True:
            try:
                self._speaker_q.get_nowait()
            except queue.Empty:
                break
        self._ring.clear()
        # Reset the soxr resampler state so the next chunk starts clean.
        self._resampler = soxr.ResampleStream(
            SPEAKER_SAMPLE_RATE,
            APM_SAMPLE_RATE,
            num_channels=1,
            dtype=np.float32,
        )

    def _reverse_worker(self) -> None:
        """Background thread: resample speaker audio and feed to APM reverse stream."""
        while True:
            chunk = self._speaker_q.get()
            if chunk is None:
                continue
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32)

            # soxr streaming resample: 24 kHz → 16 kHz, keeps internal state
            # for gapless output and is ~3-5× faster than scipy.resample_poly.
            resampled = self._resampler.resample_chunk(chunk)

            # Write into the ring-buffer (O(1), no concatenation).
            self._ring.write(resampled)

            # Drain as many complete 10 ms frames as available, feeding them
            # to the WebRTC APM in a single lock acquisition.
            frames: list[bytes] = []
            while True:
                frame = self._ring.read(APM_FRAME_SAMPLES)
                if frame is None:
                    break
                frames.append(_f32_to_int16_bytes(frame, _REV_SCRATCH_I16))

            if frames:
                with self._apm_lock:
                    for fb in frames:
                        self._ap.process_reverse_stream(fb)


aec = AcousticEchoCanceller()
