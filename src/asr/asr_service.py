
import queue
import threading
import time
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    pass

from src.asr.factory import get_asr_engine
from src.asr.denoiser import SpeechDenoiser, downsample_48k_to_16k
from src.asr.vad import VoiceActivityDetector, VoiceActivityDetectorStreaming
from src.config.logger import get_logger
from src.config.global_events import *
from src.asr.aec import aec
from src.observability import Metric, latency_tracker
from src.config.settings import SETTINGS

logger = get_logger("asr.stream")


class ASRService:
    def __init__(
        self,
        block_ms: int = 50,
        barge_in_ms: int = 150,
        partial_pause_ms: int = 400,
        end_silence_ms: int = 700,
    ):
        self.sample_rate = SETTINGS.STT_SAMPLE_RATE

        self._block_ms = block_ms
        self._frames_per_block = max(1, block_ms // 10)
        self._barge_in_blocks = max(1, barge_in_ms // block_ms)
        self._partial_pause_blocks = max(1, partial_pause_ms // block_ms)
        self._end_silence_blocks = max(1, end_silence_ms // block_ms)

        self._trailing_pad_blocks = max(1, 100 // block_ms)

        # self.vad = VoiceActivityDetector(threshold=0.7, sample_rate=self.sample_rate)
        self.vad = VoiceActivityDetectorStreaming(threshold=0.7, sample_rate=self.sample_rate)

        self._asr_config = SETTINGS.STT_CONFIG
        self.noise_suppressor = None
        self.asr = None

        self.UserAudioQueue = queue.Queue()

    def _transcribe_buffer(self, buffer: list) -> str:
        if not buffer: 
            return None

        full_audio = np.concatenate(buffer)
        audio_ms = (len(full_audio) / self.sample_rate) * 1000.0
        with latency_tracker.measure(Metric.STT_TRANSCRIBE, audio_ms=round(audio_ms)):
            return self.asr.transcribe(full_audio)

    def _yield_transcript(self, buffer):
        text = self._transcribe_buffer(buffer)

        if text.strip():
            return text
        return None

    def _is_speech_detected(self, chunk: np.ndarray) -> bool:
        return self.vad.contains_speech(chunk)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio stream status: %s", status)
        chunk_for_aec = indata[:, 0].copy()
        self.UserAudioQueue.put(aec.process_mic(chunk_for_aec))

    def set_vad_threshold(self, threshold: float):
        logger.info("VAD threshold changed to: %f", threshold)
        self.vad.change_threshold(threshold)

    def reset_vad_threshold(self):
        logger.info("VAD threshold reset to: 0.7")
        self.vad.change_threshold(0.7)

    def _ensure_models(self) -> None:
        """Lazily build the MLX models on the calling (worker) thread."""
        if self.noise_suppressor is None:
            self.noise_suppressor = SpeechDenoiser()
        if self.asr is None:
            self.asr = get_asr_engine(config=self._asr_config)

    def stream(self):
        """
        Yields partial transcription strings as the user speaks.
        Clears is_user_speaking only AFTER the final yield for an utterance,
        so the consumer always sees a consistent event + text together.
        """
        logger.info("ASR stream started")
        self._ensure_models()

        while True:
            is_asr_enabled_event.wait()

            with sd.InputStream(
                samplerate=SETTINGS.MIC_SAMPLE_RATE,
                channels=1,
                blocksize=SETTINGS.MIC_SAMPLE_RATE//100,    # 10ms of audio
                latency="high",
                callback=self._audio_callback,
            ):

                block_frames: list = []
                speech_buffer: list = []
                speech_blocks = 0
                silence_blocks = 0
                utterance_flag = False

                while IsASREnabled():
                    try:
                        frame = self.UserAudioQueue.get()
                    except queue.Empty:
                        continue

                    # Shutdown sentinel
                    if frame is None:
                        break

                    # Accumulate B ms of 10 ms mic frames before running models.
                    block_frames.append(frame)
                    if len(block_frames) < self._frames_per_block:
                        continue

                    block = np.concatenate(block_frames)
                    block_frames.clear()

                    # Denoise + downsample once per block (B ms).
                    block = self.noise_suppressor.process(block)
                    block = downsample_48k_to_16k(block)

                    speech = self._is_speech_detected(block)
                    
                    if speech:
                        utterance_flag = True
                        speech_blocks += 1
                        silence_blocks = 0
                    elif utterance_flag:
                        silence_blocks += 1

                    if not utterance_flag:
                        continue
                        
                    if speech_blocks >= self._barge_in_blocks:
                        ToggleUserBargeIn(True)

                    speech_buffer.append(block)

                    # Micro pause, generate partial transcript
                    if silence_blocks >= self._partial_pause_blocks and speech_blocks > 0:
                        text = self._yield_transcript(speech_buffer)
                        speech_blocks = 0
                        speech_buffer.clear()
                        if text:
                            yield text
                    
                    # End of user speaking, reset all flags
                    if silence_blocks >= self._end_silence_blocks:
                        self.vad.reset()
                        ToggleUserBargeIn(False)
                        utterance_flag = False
                        silence_blocks = 0
                        speech_blocks = 0
                        speech_buffer.clear()
                        yield None