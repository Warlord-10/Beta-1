
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

logger = get_logger("asr.stream")


class ASRService:
    def __init__(
        self,
        is_user_speaking: threading.Event = None,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 500,
        max_silence_chunks: int = 6,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(self.sample_rate * (chunk_duration_ms / 1000.0))
        self.max_silence_chunks = max_silence_chunks

        # self.noise_suppressor = NoiseSuppressor(target_sample_rate=sample_rate)
        self.vad = VoiceActivityDetector(threshold=0.7)
        self.asr = get_asr_engine()

        self.is_user_speaking = is_user_speaking
        self._audio_queue: queue.Queue = queue.Queue()
        self._speech_buffer: list = []
        self._silence_chunks: int = 0


    def _transcribe_buffer(self, buffer: list) -> str:
        if not buffer:
            return ""
        full_audio = np.concatenate(buffer)
        return self.asr.transcribe(full_audio, self.sample_rate)

    def _yield_transcript(self):
        temp_buffer = self._speech_buffer.copy()
        text = self._transcribe_buffer(temp_buffer)
        self._speech_buffer.clear()

        if text.strip():
            print("Final transcript: %r", text)
            return text

    def _is_speech(self, chunk: np.ndarray) -> bool:
        return self.vad.contains_speech(chunk, self.sample_rate)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio stream status: %s", status)
        self._audio_queue.put(indata[:, 0].copy())

    def _set_speaking(self, speaking: bool) -> None:
        if self.is_user_speaking is None:
            return
        if speaking:
            self.is_user_speaking.set()
        else:
            self.is_user_speaking.clear()


    def stream(self):
        """
        Yields partial transcription strings as the user speaks.
        Clears is_user_speaking only AFTER the final yield for an utterance,
        so the consumer always sees a consistent event + text together.
        """
        logger.info("ASR stream started")
        self._speech_buffer.clear()
        self._silence_chunks = 0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=self.chunk_size,
            callback=self._audio_callback,
        ):

            current_speech_chunk = 0
            while True:
                try:
                    chunk = self._audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Shutdown sentinel
                if chunk is None:
                    break

                chunk = self.noise_suppressor.process(chunk, self.sample_rate)
                is_speech = self._is_speech(chunk)
                self._speech_buffer.append(chunk)

                if is_speech:
                    self._silence_chunks = 0
                    current_speech_chunk += 1
                    self._set_speaking(True)
                    print("Speech detected")
                else:
                    self._silence_chunks += 1
                    print("Silence gap: %d", self._silence_chunks)

                # Partial transcription on short silence — user still speaking
                if self._silence_chunks == 2 and len(self._speech_buffer) > 0 and current_speech_chunk > 0:
                    current_speech_chunk = 0
                    yield self._yield_transcript()

                # End of utterance — clear event AFTER yielding final chunk
                if self._silence_chunks >= self.max_silence_chunks:
                    self._silence_chunks = 0
                    current_speech_chunk = 0

                    # Flush any remaining audio
                    if self._speech_buffer:
                        yield self._yield_transcript()

                    # Only now signal that the user has stopped speaking
                    self._set_speaking(False)
                    print("End of utterance")