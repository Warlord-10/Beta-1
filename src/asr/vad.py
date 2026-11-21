"""Voice Activity Detection: Silero VAD run directly on onnxruntime.

The ``silero_vad`` package wraps the ONNX model in torch tensors, which costs
~170 MB of RAM just to import torch. This runs the same model file with numpy
and keeps the same start/stop logic as silero's ``VADIterator``.
"""

import math
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import onnxruntime

from src.config.logger import get_logger

logger = get_logger("asr.vad")

# The model file shipped with the silero_vad package. find_spec locates the
# package without importing it (importing it would load torch).
_MODEL_PATH = Path(find_spec("silero_vad").submodule_search_locations[0]) / "data" / "silero_vad.onnx"

# Speech ends after this long below (threshold - _HYSTERESIS), as in VADIterator.
_MIN_SILENCE_MS = 100
_HYSTERESIS = 0.15


class VoiceActivityDetectorStreaming:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        if sample_rate not in (8000, 16000):
            raise ValueError("Silero VAD supports only 8000 or 16000 Hz")

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(
            str(_MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"]
        )

        self.threshold = threshold
        self.sample_rate = sample_rate
        self.window_size = 512 if sample_rate == 16000 else 256
        self._context_size = 64 if sample_rate == 16000 else 32
        self._min_silence_windows = math.ceil(sample_rate * _MIN_SILENCE_MS / 1000 / self.window_size)
        self._sr = np.array(sample_rate, dtype=np.int64)
        self.reset()
        logger.info(
            "Loaded streaming Silero VAD (threshold=%.2f, sr=%d, window=%d)",
            threshold, sample_rate, self.window_size,
        )

    def contains_speech(self, audio: np.ndarray) -> bool:
        # Accumulate, then run the model on each full window in order; the
        # remainder (<window_size) stays buffered for the next call.
        self.internal_buffer = np.concatenate([self.internal_buffer, audio.reshape(-1).astype(np.float32)])
        try:
            while self.internal_buffer.size >= self.window_size:
                window = self.internal_buffer[: self.window_size]
                self.internal_buffer = self.internal_buffer[self.window_size :]
                self._update(self._speech_prob(window))
        except Exception as e:
            logger.error(f"VAD Error: {e}")
            return False
        return self.triggered

    def _speech_prob(self, window: np.ndarray) -> float:
        x = np.concatenate([self._context, window])[np.newaxis, :]
        prob, self._state = self.session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = window[-self._context_size :]
        return float(prob[0, 0])

    def _update(self, prob: float) -> None:
        """Start on prob >= threshold. Stop once _MIN_SILENCE_MS has passed since
        the first window clearly below it, with no speech window in between."""
        self._window += 1
        if prob >= self.threshold:
            self.triggered = True
            self._silence_from = 0
        elif self.triggered and prob < self.threshold - _HYSTERESIS:
            self._silence_from = self._silence_from or self._window
            if self._window - self._silence_from >= self._min_silence_windows:
                self.triggered = False
                self._silence_from = 0

    def change_threshold(self, threshold: float):
        self.threshold = threshold

    def reset(self):
        """Clear streaming state. Call between utterances / on barge-in."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self._context_size, dtype=np.float32)
        self.triggered = False
        self._window = 0
        self._silence_from = 0
        self.internal_buffer = np.empty(0, dtype=np.float32)


if __name__ == "__main__":
    # Self-check: same speech decisions as silero's VADIterator, window by window.
    # Usage: python -m src.asr.vad <speech.wav, 16 kHz mono>
    import sys

    import soundfile as sf
    import torch
    from silero_vad import VADIterator, load_silero_vad

    audio, sr = sf.read(sys.argv[1], dtype="float32")
    assert sr == 16000, "needs a 16 kHz file"
    ours = VoiceActivityDetectorStreaming(threshold=0.5)
    ref = VADIterator(load_silero_vad(onnx=True), threshold=0.5)
    windows = speech = mismatches = 0
    for i in range(0, audio.size - 511, 512):
        window = audio[i : i + 512]
        is_speech = ours.contains_speech(window)
        ref(torch.from_numpy(window))
        windows += 1
        speech += is_speech
        mismatches += is_speech != ref.triggered
    print(f"{windows} windows, {speech} speech, {mismatches} mismatches")
    assert mismatches == 0 and speech > 0
