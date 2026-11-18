import asyncio
import queue

from src.config.global_queues import UserInputQueue

class IO:
    def __init__(self):
        self.input_queue = UserInputQueue

    def push_to_llm(self, message):
        self.input_queue.put(message)

    def get_from_llm(self):
        return self.input_queue.get(timeout=0.25)

    async def async_get_from_llm(self) -> str:
        # Timeout so the executor thread frees up and asyncio.run can exit.
        while True:
            try:
                return await asyncio.to_thread(self.input_queue.get, timeout=0.25)
            except queue.Empty:
                continue

    async def async_push_to_llm(self, message: str) -> None:
        await asyncio.to_thread(self.input_queue.put, message)
        