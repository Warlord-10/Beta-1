from src.config.global_queues import UserInputQueue

class IO:
    def __init__(self):
        self.input_queue = UserInputQueue

    def push_to_llm(self, message):
        self.input_queue.put(message)

    def get_from_llm(self):
        return self.input_queue.get(timeout=0.25)
        