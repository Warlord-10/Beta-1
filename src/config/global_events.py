"""Cross-thread flags and queues.

Everything in Beta-1 is thread-based; nothing here is async. The chat-loop,
workflow-loop, ASR worker, TTS worker, and the TUI all coordinate through
these primitives.
"""

import threading


is_user_speaking_event: threading.Event = threading.Event()
is_tts_enabled_event: threading.Event = threading.Event()
is_asr_enabled_event: threading.Event = threading.Event()
workflow_active_event: threading.Event = threading.Event()

def CheckUserBargeIn() -> bool:
    return is_user_speaking_event.is_set()

def ToggleUserBargeIn(value: bool) -> None:
    if value:
        is_user_speaking_event.set()
    else:
        is_user_speaking_event.clear()

def IsTTSEnabled() -> bool:
    return is_tts_enabled_event.is_set()

def ToggleTTS(value: bool) -> None:
    if value:
        is_tts_enabled_event.set()
    else:
        is_tts_enabled_event.clear()

def IsASREnabled() -> bool:
    return is_asr_enabled_event.is_set()

def ToggleASR(value: bool) -> None:
    if value:
        is_asr_enabled_event.set()
    else:
        is_asr_enabled_event.clear()

def IsWorkflowActive() -> bool:
    return workflow_active_event.is_set()

def ToggleWorkflow(value: bool) -> None:
    if value:
        workflow_active_event.set()
    else:
        workflow_active_event.clear()


