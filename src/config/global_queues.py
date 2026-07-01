from queue import Queue

# User → chat agent (one item per user turn).
UserInputQueue: Queue = Queue()
# Chat agent → TTS worker (sentence-chunked).
LLMChunkQueue: Queue = Queue()

# Chat agent (via delegate_to_planner) → workflow-loop. Serialised: the
# workflow-loop handles one task at a time, queueing further requests.
ComplexTaskQueue: Queue = Queue()
# TUI → workflow-loop, carrying the user's plan-review verdict. The
# request side flows through the listener (PipelineListener.on_plan_review)
# so the TUI is notified directly rather than polling a queue.
PlanReviewResponseQueue: Queue = Queue()

def DrainLLMQueue():
    while not LLMChunkQueue.empty():
        try:
            LLMChunkQueue.get_nowait()
        except queue.Empty:
            return