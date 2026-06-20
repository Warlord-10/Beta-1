
import queue
import threading
import time
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    pass

from src.asr.factory import get_asr_engine
# from src.asr.noise_suppressor import NoiseSuppressor
from src.asr.vad import VoiceActivityDetector
from src.config.logger import get_logger
from src.config.global_events import *
from src.asr.aec import aec
from src.observability import Metric, latency_tracker

logger = get_logger("asr.stream")


class ASRService:
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 10,
        max_silence_chunks: int = 6,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(self.sample_rate * (chunk_duration_ms / 1000.0))
        self.max_silence_chunks = max_silence_chunks

        # self.noise_suppressor = NoiseSuppressor(target_sample_rate=sample_rate)
        self.vad = VoiceActivityDetector(threshold=0.7)
        self.asr = get_asr_engine()

        self.UserAudioQueue = queue.Queue()
        self._speech_buffer: list = []
        self._silence_chunks: int = 0


    def _transcribe_buffer(self, buffer: list) -> str:
        if not buffer:
            return ""
        full_audio = np.concatenate(buffer)
        audio_ms = (len(full_audio) / self.sample_rate) * 1000.0
        with latency_tracker.measure(Metric.STT_TRANSCRIBE, audio_ms=round(audio_ms)):
            return self.asr.transcribe(full_audio, self.sample_rate)

    def _yield_transcript(self):
        temp_buffer = self._speech_buffer.copy()
        text = self._transcribe_buffer(temp_buffer)
        self._speech_buffer.clear()

        if text.strip():
            print("Final transcript: ", text)
            return text

    def _is_speech_detected(self, chunk: np.ndarray) -> bool:
        return self.vad.contains_speech(chunk, self.sample_rate)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio stream status: %s", status)
        chunk_for_aec = indata[:, 0].copy()
        self.UserAudioQueue.put(aec.process_mic(chunk_for_aec))

    def _reset_silence_chunks(self):
        self._silence_chunks = 0

    def _can_process_partial_transcript(self):
        pass

    def _can_process_complete_transcript(self):
        pass

    def set_vad_threshold(self, threshold: float):
        logger.info("VAD threshold changed to: %f", threshold)
        self.vad.change_threshold(threshold)

    def reset_vad_threshold(self):
        logger.info("VAD threshold reset to: 0.7")
        self.vad.change_threshold(0.7)

    def stream(self):
        """
        Yields partial transcription strings as the user speaks.
        Clears is_user_speaking only AFTER the final yield for an utterance,
        so the consumer always sees a consistent event + text together.
        """
        logger.info("ASR stream started")
        self._speech_buffer.clear()
        self._silence_chunks = 0

        while True:
            is_asr_enabled_event.wait()

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.chunk_size,
                latency="high",
                callback=self._audio_callback,
            ):

                current_speech_chunk = 0
                vad_buffer = []

                while IsASREnabled():
                    try:
                        chunk = self.UserAudioQueue.get()
                    except queue.Empty:
                        continue

                    # Shutdown sentinel
                    if chunk is None:
                        break

                    # Check if enough chunks are present for VAD
                    vad_buffer.append(chunk)
                    if len(vad_buffer) < 25:
                        continue

                    chunk = np.concatenate(vad_buffer)
                    vad_buffer.clear()

                    self._speech_buffer.append(chunk)

                    if self._is_speech_detected(chunk):
                        print("detected speech")
                        self._reset_silence_chunks()
                        current_speech_chunk += 1
                    else:
                        self._silence_chunks += 1

                    # To prevent false barge ins
                    if current_speech_chunk > 2:
                        ToggleUserBargeIn(True)

                    # Partial transcription on short silence — user still speaking
                    if self._silence_chunks == 2 and current_speech_chunk > 0:
                        current_speech_chunk = 0
                        yield self._yield_transcript()

                    # End of utterance — clear event AFTER yielding final chunk
                    if self._silence_chunks >= self.max_silence_chunks:
                        self._reset_silence_chunks()
                        current_speech_chunk = 0

                        # Flush any remaining audio
                        self._speech_buffer.clear()
                        ToggleUserBargeIn(False)
                        yield None