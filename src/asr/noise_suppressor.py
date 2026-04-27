"""Background noise suppression using DeepFilterNet.

Layered before the VAD/ASR. Accepts 16 kHz mono float32 numpy arrays and
returns denoised audio at the same shape and sample rate. DeepFilterNet
runs natively at 48 kHz, so input is resampled up, denoised, and
resampled back.
"""

from __future__ import annotations

import numpy as np

from src.config.logger import get_logger

logger = get_logger("asr.noise_suppressor")

_DF_NATIVE_SR = 48000


class NoiseSuppressor:
    """Streaming-friendly DeepFilterNet wrapper.

    Each call to `process(chunk, sample_rate)` is independent at the API
    level but DeepFilterNet maintains short-context state internally for
    the duration of a single call. For 500 ms chunks the boundary
    artifacts are inaudible to the downstream VAD/ASR.
    """

    def __init__(self, target_sample_rate: int = 16000) -> None:
        self.target_sample_rate = target_sample_rate
        self._model = None
        self._df_state = None
        self._torch = None
        self._torchaudio_resample = None
        self._enhance = None

        try:
            import torch
            from df.enhance import enhance, init_df

            self._torch = torch
            model, df_state, _ = init_df()
            model.eval()
            self._model = model
            self._df_state = df_state
            self._enhance = enhance

            from torchaudio.functional import resample

            self._torchaudio_resample = resample
            logger.info(
                "NoiseSuppressor ready (DeepFilterNet @ %d Hz, target=%d Hz)",
                _DF_NATIVE_SR,
                target_sample_rate,
            )
        except Exception:
            logger.exception(
                "NoiseSuppressor disabled — DeepFilterNet not available. "
                "Install with: uv add deepfilternet"
            )

    @property
    def enabled(self) -> bool:
        return self._model is not None

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Denoise a mono float32 chunk. Returns audio at the original rate."""
        if not self.enabled:
            return audio

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        torch = self._torch
        try:
            tensor = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)

            if sample_rate != _DF_NATIVE_SR:
                tensor = self._torchaudio_resample(
                    tensor, sample_rate, _DF_NATIVE_SR
                )

            with torch.no_grad():
                enhanced = self._enhance(self._model, self._df_state, tensor)

            if sample_rate != _DF_NATIVE_SR:
                enhanced = self._torchaudio_resample(
                    enhanced, _DF_NATIVE_SR, sample_rate
                )

            out = enhanced.squeeze(0).cpu().numpy().astype(np.float32)

            # Resampling can produce off-by-one length differences — pad/trim
            if out.shape[0] != audio.shape[0]:
                if out.shape[0] > audio.shape[0]:
                    out = out[: audio.shape[0]]
                else:
                    out = np.pad(out, (0, audio.shape[0] - out.shape[0]))
            return out
        except Exception:
            logger.exception("Denoise failed — passing audio through unchanged")
            return audio
