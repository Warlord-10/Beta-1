from dataclasses import dataclass, field
from queue import Queue
import threading


class GlobalEvents:
    is_user_speaking_event: threading.Event = threading.Event()

    @classmethod
    def is_user_speaking(cls) -> bool:
        return cls.is_user_speaking_event.is_set()

    @classmethod
    def set_user_speaking(cls, value: bool) -> None:
        if value:
            cls.is_user_speaking_event.set()
        else:
            cls.is_user_speaking_event.clear()

class GlobalQueues:
    llm_chunk_queue: Queue = Queue()
    input_queue: Queue = Queue()
    audio_chunk_queue: Queue = Queue()


