from src.config.events import GlobalQueues

class IO:
    def __init__(self):
        self.input_queue = GlobalQueues.input_queue

    def push_to_llm(self, message):
        self.input_queue.put(message)