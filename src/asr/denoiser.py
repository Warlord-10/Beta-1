"""Neural speech enhancement (noise suppression) via DeepFilterNet on MLX.

DeepFilterNet is a low-complexity, full-band (48 kHz) speech-enhancement model.
This wrapper runs the MLX (Apple-Silicon) port shipped with ``mlx_audio`` in
true streaming mode so it can sit on the live mic path and clean audio
frame-by-frame.

Pipeline placement::

    mic @ 48 kHz ── SpeechDenoiser.process ──▶ clean @ 48 kHz
                                                     │
                                  downsample_48k_to_16k
                                                     ▼
                                      AEC / VAD / ASR @ 16 kHz

The model only understands 48 kHz, while the rest of the ASR stack runs at
16 kHz — hence :func:`downsample_48k_to_16k`, which is the last step before the
cleaned audio is handed downstream.
"""

from __future__ import annotations

import numpy as np
import soxr

from mlx_audio.sts.models.deepfilternet import DeepFilterNetModel

from src.config.logger import get_logger

logger = get_logger("asr.denoiser")

# DeepFilterNet is trained for full-band 48 kHz audio. This is fixed by the model.
DF_SAMPLE_RATE = 48000
# Target rate for the downstream ASR / AEC / VAD stack.
TARGET_SAMPLE_RATE = 16000


class SpeechDenoiser:
    """Streaming DeepFilterNet noise suppressor.

    Instantiate once, then feed it 48 kHz float32 audio chunks via
    :meth:`process`; it returns the cleaned 48 kHz audio for the same span.
    State persists across calls (overlap buffers, normalization EMAs, GRU
    hidden states), so call :meth:`reset` whenever the stream is discontinuous
    (e.g. on barge-in or a new utterance).
    """

    def __init__(self, version: int = 3) -> None:
        # v3 is the latest/best; v1/v2 are smaller. Streaming requires v2/v3.
        self.model = DeepFilterNetModel.from_pretrained(version=version)
        self.sample_rate = self.model.config.sample_rate  # 48000
        self._streamer = self.model.create_streamer()
        logger.info(
            "SpeechDenoiser loaded (DeepFilterNet v%d, %d Hz, hop=%d)",
            version,
            self.sample_rate,
            self.model.config.hop_size,
        )

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Denoise one 48 kHz float32 chunk and return the cleaned 48 kHz audio.

        Accepts any chunk length; the streamer buffers partial hops internally,
        so the returned array may be slightly shorter or longer than the input.
        """
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return self._streamer.process_chunk(audio)

    def reset(self) -> None:
        """Drop all streaming state. Call on barge-in or between utterances."""
        self._streamer.reset()


def downsample_48k_to_16k(audio: np.ndarray) -> np.ndarray:
    """Resample 48 kHz → 16 kHz float32 audio for the ASR/AEC/VAD stack.

    One-shot, high-quality resample via libsoxr. For gapless frame-by-frame
    streaming use a persistent ``soxr.ResampleStream`` instead (see
    ``src/asr/aec.py``); for whole utterance buffers this is exact and simplest.
    """
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    return soxr.resample(audio, DF_SAMPLE_RATE, TARGET_SAMPLE_RATE)
