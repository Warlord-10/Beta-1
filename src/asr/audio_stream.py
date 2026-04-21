"""Audio streaming module using SoundDevice, VAD, and ASR."""

import queue
import time

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    pass

from src.asr.factory import get_asr_engine
from src.asr.vad import VoiceActivityDetector
from src.config.logger import get_logger

logger = get_logger("asr.stream")


class ASRStream:
    def __init__(self, sample_rate: int = 16000, chunk_duration_ms: int = 500, max_silence_chunk: int = 8):
        self.sample_rate = sample_rate
        self.chunk_size = int(self.sample_rate * (chunk_duration_ms / 1000.0))
        
        self.vad = VoiceActivityDetector(threshold=0.7)
        self.asr = get_asr_engine()
        
        self.audio_queue = queue.Queue()
        self.is_listening = False

        self.speech_buffer = []

        self.max_silence_chunk = max_silence_chunk
        self.silence_chunks = 0

    def _get_transcription(self):
        full_audio = np.concatenate(self.speech_buffer)
        text = self.asr.transcribe(full_audio, self.sample_rate)
        return text

    def _is_speech_present(self, audio_chunk):
        return self.vad.contains_speech(audio_chunk, self.sample_rate)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio stream status: {status}")

        audio_data = indata[:, 0]
        self.audio_queue.put(audio_data.copy())
        # print("Got some audio")
        

    def listen(self):
        print("Listening...")
        self.is_listening = True

        with sd.InputStream(
            samplerate=self.sample_rate, 
            channels=1, 
            blocksize=self.chunk_size,
            callback=self._audio_callback
        ):
            while self.is_listening:
                try:
                    audio_chunk = self.audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Speech detection
                if self._is_speech_present(audio_chunk):
                    self.speech_buffer.append(audio_chunk)
                    self.silence_chunks = 0
                else:
                    self.silence_chunks += 1
                    self.speech_buffer.append(audio_chunk)

                # End of speech detection
                if self.silence_chunks >= self.max_silence_chunk:    
                    self.is_listening = False
                    print("Speech ended. Transcribing...")

        return self._get_transcription()

    def stream(self):
        print("Listening...")
        self.is_listening = True
        final_text = []

        with sd.InputStream(
            samplerate=self.sample_rate, 
            channels=1, 
            blocksize=self.chunk_size,
            callback=self._audio_callback
        ):
            while self.is_listening:
                try:
                    audio_chunk = self.audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Speech detection
                if self._is_speech_present(audio_chunk):
                    self.speech_buffer.append(audio_chunk)
                    self.silence_chunks = 0
                    print("Speech detected")
                else:
                    self.silence_chunks += 1
                    self.speech_buffer.append(audio_chunk)
                    print("Silence detected: ", self.silence_chunks)

                # Live Transcribing
                if len(self.speech_buffer) > 0 and self.silence_chunks >= 2:
                    text = self._get_transcription()
                    self.speech_buffer = []
                    final_text.append((time.time(), text))
                    yield text

                # End of speech detection
                if self.silence_chunks >= self.max_silence_chunk:
                    self.is_listening = False
                

        # return final_text