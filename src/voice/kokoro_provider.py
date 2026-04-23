"""Kokoro TTS Provider."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

from src.config.logger import get_logger
from src.utils.text_utils import clean_text
from src.voice.base import BaseTTS

logger = get_logger("voice.kokoro")


class KokoroTTS(BaseTTS):
    """Kokoro TTS integration for Beta-1."""

    def __init__(self, voice_name: str = "af_heart", sample_rate: int = 24000, speed: float = 1.0):
        if KPipeline is None:
            raise RuntimeError("kokoro package is not installed. Run: uv sync")

        self.sample_rate = sample_rate
        self.voice_name = voice_name
        self.speed = speed
        self.audio_queue = queue.Queue()

        lang_code = voice_name[0] if voice_name else 'a'

        logger.info("Initializing Kokoro TTS pipeline (lang=%s)...", lang_code)
        self.pipeline = KPipeline(lang_code=lang_code)
        logger.info("Kokoro TTS initialized with voice: %s (speed: %.1f)", self.voice_name, self.speed)

    def synthesize(self, text: str, word_callback: Optional[Callable[[str], None]] = None) -> None:
        """Synthesize text and enqueue audio.

        Streams the first Kokoro segment to minimise first-audio latency while
        synthesising remaining segments concurrently so word timing is available.

        Args:
            text: Text to synthesise.
            word_callback: Called with each word string at the moment that word
                           is estimated to start playing. Runs on a daemon thread.
        """
        if not text.strip():
            return

        text = clean_text(text)

        try:
            logger.debug("Synthesizing: %r", text[:60])
            generator = self.pipeline(
                text,
                voice=self.voice_name,
                speed=self.speed,
                split_pattern=r'\n+',
            )

            # Collect all segments to compute per-word offsets.
            # Each segment: (grapheme_text, audio_array).
            segments: list[tuple[str, np.ndarray]] = []
            for gs, _ps, audio in generator:
                segments.append((gs or "", audio))

            if not segments:
                return

            # Build per-word (word, playback_offset_seconds) schedule.
            words_with_offsets: list[tuple[str, float]] = []
            cursor = 0.0  # seconds from start of this synthesize() call
            for gs, audio in segments:
                chunk_duration = len(audio) / self.sample_rate
                words = gs.strip().split()
                n = len(words)
                for i, word in enumerate(words):
                    words_with_offsets.append((word, cursor + (i / max(1, n)) * chunk_duration))
                cursor += chunk_duration

            # The _on_start sentinel is processed by the stream callback at the
            # exact frame when audio begins. It spawns a lightweight timer thread
            # that fires word_callback at each word's estimated onset time.
            def _on_start():
                t0 = time.monotonic()

                def _printer():
                    for word, offset in words_with_offsets:
                        remaining = offset - (time.monotonic() - t0)
                        if remaining > 0:
                            time.sleep(remaining)
                        try:
                            word_callback(word)
                        except Exception:
                            pass

                if word_callback:
                    threading.Thread(target=_printer, daemon=True).start()

            # Enqueue sentinel first, then audio — so text starts when audio starts.
            self.audio_queue.put(('_on_start', _on_start))
            for _gs, audio in segments:
                self.audio_queue.put(audio)

        except Exception as e:
            logger.error("Kokoro synthesis failed: %s", str(e))

    def play(self, text: str, block: bool = True) -> None:
        while not self.audio_queue.empty():
            audio = self.audio_queue.get()
            if isinstance(audio, tuple):
                continue
            sd.play(audio, samplerate=self.sample_rate)
            sd.wait()

    def stream(self):
        leftover = np.array([], dtype='float32')

        def callback(outdata, frames, time, status):
            nonlocal leftover
            needed = frames
            result = leftover

            if status:
                print(f"Status: {status}")

            while len(result) < needed:
                try:
                    chunk = self.audio_queue.get_nowait()
                    if chunk is None:
                        break
                    if isinstance(chunk, tuple) and chunk[0] == '_on_start':
                        try:
                            chunk[1]()  # spawns word-printer thread
                        except Exception:
                            pass
                        continue
                    result = np.concatenate([result, chunk])
                except queue.Empty:
                    break

            if len(result) >= needed:
                outdata[:] = result[:needed].reshape(-1, 1)
                leftover = result[needed:]
            else:
                outdata[:len(result)] = result.reshape(-1, 1)
                outdata[len(result):] = 0
                leftover = np.array([], dtype='float32')

        return sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='float32',
            callback=callback,
        )
