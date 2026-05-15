"""Cross-thread flags and queues.

Everything in Beta-1 is thread-based; nothing here is async. The chat-loop,
workflow-loop, ASR worker, TTS worker, and the TUI all coordinate through
these primitives.
"""

import threading
from queue import Queue


class GlobalEvents:
    """Boolean flags shared across threads."""

    is_user_speaking_event: threading.Event = threading.Event()
    is_tts_enabled_event: threading.Event = threading.Event()
    is_asr_enabled_event: threading.Event = threading.Event()
    # True while the workflow-loop is executing a complex task.
    workflow_active_event: threading.Event = threading.Event()

    @classmethod
    def is_user_speaking(cls) -> bool:
        return cls.is_user_speaking_event.is_set()

    @classmethod
    def set_user_speaking(cls, value: bool) -> None:
        (cls.is_user_speaking_event.set if value
         else cls.is_user_speaking_event.clear)()

    @classmethod
    def is_tts_enabled(cls) -> bool:
        return cls.is_tts_enabled_event.is_set()

    @classmethod
    def set_tts_enabled(cls, value: bool) -> None:
        (cls.is_tts_enabled_event.set if value
         else cls.is_tts_enabled_event.clear)()

    @classmethod
    def is_asr_enabled(cls) -> bool:
        return cls.is_asr_enabled_event.is_set()

    @classmethod
    def set_asr_enabled(cls, value: bool) -> None:
        (cls.is_asr_enabled_event.set if value
         else cls.is_asr_enabled_event.clear)()

    @classmethod
    def is_workflow_active(cls) -> bool:
        return cls.workflow_active_event.is_set()

    @classmethod
    def set_workflow_active(cls, value: bool) -> None:
        (cls.workflow_active_event.set if value
         else cls.workflow_active_event.clear)()


class GlobalQueues:
    """Message queues shared across threads.

    Producers and consumers live on different threads; reading is always
    blocking-with-timeout so workers can poll their stop flags.
    """

    # User → chat agent (one item per user turn).
    input_queue: Queue = Queue()
    # Chat agent → TTS worker (sentence-chunked).
    llm_chunk_queue: Queue = Queue()
    # ASR worker → ?? (legacy slot; not currently consumed).
    audio_chunk_queue: Queue = Queue()

    # Chat agent (via delegate_to_planner) → workflow-loop. Serialised: the
    # workflow-loop handles one task at a time, queueing further requests.
    complex_task_queue: Queue = Queue()
    # TUI → workflow-loop, carrying the user's plan-review verdict. The
    # request side flows through the listener (PipelineListener.on_plan_review)
    # so the TUI is notified directly rather than polling a queue.
    plan_review_response_queue: Queue = Queue()
