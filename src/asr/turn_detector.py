"""Semantic end-of-turn detection via Pipecat's Smart Turn v3.

Smart Turn is a small (~8M param, Whisper-tiny backbone) classifier that decides
whether a user has *finished* their turn or merely paused mid-thought, using
acoustic + linguistic cues rather than raw silence. It complements — it does not
replace — the Silero VAD: run a cheap VAD to find candidate silences, then call
Smart Turn only during those silences to confirm a real end-of-turn.

Input is 16 kHz mono float32 audio (the full turn so far, auto-truncated to the
last 8 s). Inference runs on CPU via ONNX Runtime in ~10-30 ms.
"""

from __future__ import annotations

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from transformers import WhisperFeatureExtractor

from src.config.logger import get_logger

logger = get_logger("asr.turn")

SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
DEFAULT_ONNX_FILE = "smart-turn-v3.2-cpu.onnx"

SAMPLE_RATE = 16000
MAX_SECONDS = 8
MAX_SAMPLES = MAX_SECONDS * SAMPLE_RATE


def _truncate_or_pad(audio: np.ndarray) -> np.ndarray:
    """Keep the last 8 s, or left-pad with zeros up to 8 s."""
    if len(audio) > MAX_SAMPLES:
        return audio[-MAX_SAMPLES:]
    if len(audio) < MAX_SAMPLES:
        return np.pad(audio, (MAX_SAMPLES - len(audio), 0), mode="constant")
    return audio


class TurnDetector:
    """Smart Turn v3 end-of-turn classifier.

    Instantiate once (downloads the ONNX weights on first use), then call
    :meth:`process` with the accumulated 16 kHz turn audio. Returns a dict::

        {"prediction": 1, "probability": 0.83}

    ``prediction`` is 1 for a complete turn (safe to respond) and 0 for an
    incomplete one (the user is likely to continue).
    """

    def __init__(self, onnx_file: str = DEFAULT_ONNX_FILE, threshold: float = 0.5) -> None:
        self.threshold = threshold

        onnx_path = hf_hub_download(repo_id=SMART_TURN_REPO, filename=onnx_file)

        so = ort.SessionOptions()
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(onnx_path, sess_options=so)

        # Whisper feature extractor configured for the model's 8 s window.
        self.feature_extractor = WhisperFeatureExtractor(chunk_length=MAX_SECONDS)

        logger.info("TurnDetector loaded (%s, threshold=%.2f)", onnx_file, threshold)

    def process(self, audio: np.ndarray) -> dict:
        """Classify the turn. ``audio`` is 16 kHz mono float32 of the turn so far."""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        audio = _truncate_or_pad(audio)

        inputs = self.feature_extractor(
            audio,
            sampling_rate=SAMPLE_RATE,
            return_tensors="np",
            padding="max_length",
            max_length=MAX_SAMPLES,
            truncation=True,
            do_normalize=True,
        )
        input_features = inputs.input_features.squeeze(0).astype(np.float32)
        input_features = np.expand_dims(input_features, axis=0)

        outputs = self.session.run(None, {"input_features": input_features})
        probability = float(outputs[0][0].item())

        return {
            "prediction": 1 if probability > self.threshold else 0,
            "probability": probability,
        }

    def is_complete(self, audio: np.ndarray) -> bool:
        """Convenience boolean: True when the turn looks finished."""
        return self.process(audio)["prediction"] == 1
