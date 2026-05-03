import queue
import threading

import numpy as np
from aec_audio_processing import AudioProcessor
from scipy.signal import resample_poly

# WebRTC APM only supports 8/16/32/48 kHz. Speaker stream is resampled 24k -> 16k internally.
MIC_SAMPLE_RATE = 16000
SPEAKER_SAMPLE_RATE = 24000
APM_SAMPLE_RATE = 16000
FRAME_MS = 10
MIC_FRAME_SAMPLES = MIC_SAMPLE_RATE * FRAME_MS // 1000      # 160
APM_FRAME_SAMPLES = APM_SAMPLE_RATE * FRAME_MS // 1000      # 160
SPEAKER_FRAME_SAMPLES = SPEAKER_SAMPLE_RATE * FRAME_MS // 1000  # 240

# Round-trip delay between a sample fed to process_reverse_stream and the same
# echo arriving at process_stream. With sounddevice latency="high" on macOS this
# is typically 150-250 ms.
STREAM_DELAY_MS = 200


def _f32_to_int16_bytes(x: np.ndarray) -> bytes:
    return np.clip(x * 32768.0, -32768, 32767).astype(np.int16).tobytes()


def _int16_bytes_to_f32(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0


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

        self._apm_lock = threading.Lock()
        self._speaker_q = queue.Queue(maxsize=64)
        self._speaker_buf = np.empty(0, dtype=np.float32)
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
            cleaned = self._ap.process_stream(_f32_to_int16_bytes(chunk))
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
        self._speaker_buf = np.empty(0, dtype=np.float32)

    def _reverse_worker(self) -> None:
        while True:
            chunk = self._speaker_q.get()
            if chunk is None:
                continue
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32)
            resampled = resample_poly(chunk, up=2, down=3).astype(np.float32)
            self._speaker_buf = np.concatenate([self._speaker_buf, resampled])
            while self._speaker_buf.shape[0] >= APM_FRAME_SAMPLES:
                frame = self._speaker_buf[:APM_FRAME_SAMPLES]
                self._speaker_buf = self._speaker_buf[APM_FRAME_SAMPLES:]
                with self._apm_lock:
                    self._ap.process_reverse_stream(_f32_to_int16_bytes(frame))


aec = AcousticEchoCanceller()
