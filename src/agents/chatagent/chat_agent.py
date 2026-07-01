from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import HarmBlockThreshold, HarmCategory
from langgraph.checkpoint.memory import InMemorySaver

from src.config.global_events import *
from src.config.global_queues import *
from src.config.logger import get_logger
from src.llms import llm_factory
from src.observability import Metric, Stopwatch, latency_tracker
from src.prompts import load_prompt
from src.states.main_state import ChatState

# Read-only file tools
from src.tools.file_tools import (
    get_file_info, 
    list_directory, 
    read_file,
    search_content,
    search_files
)
# Memory tools
from src.tools.memory_tools.daily_memory_tools import (
    add_to_daily_memory,
    read_daily_memory
)
# Scheduler tools
from src.tools.scheduler_tools import (
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task
)
# Web search (lightweight — deep research goes through delegate_to_planner)
from src.tools.search_tools import regular_search
# Safe system tools
from src.tools.system_tools.safe_bash import safe_bash

logger = get_logger("agents.chat_agent")


@tool
def delegate_to_planner(task_summary: str) -> str:
    """Delegate a complex task to the planning workflow.
        Args: 
            task_summary: Summary of the task to be delegated
        Returns: 
            Confirmation message of the delegated task.
    """

    ComplexTaskQueue.put(task_summary)

    return f"""The task has been delegated, final update will be provided once it is completed.
    Tell the user that you will update him once this task is completed.
    """


CHAT_AGENT_TOOLS = [
    # File inspection
    read_file,
    list_directory,
    get_file_info,
    search_files,
    search_content,
    safe_bash,

    # Web search (quick lookups)
    regular_search,

    # Delegation
    delegate_to_planner,

    # Scheduler
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task,

    # Memory
    add_to_daily_memory,
    read_daily_memory,
]


class ChatAgent:
    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        self.llm = llm_factory.create(
            "GEMMA_4_31B",
            temperature=1,
            max_tokens=256,
            safety_settings={
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            },
            thinking_level="minimal",
        )

        self.agent = create_agent(
            model=self.llm,
            tools=CHAT_AGENT_TOOLS,
            system_prompt=load_prompt("chat_agent"),
            checkpointer=self.checkpointer,
            state_schema=ChatState,
        )

    def format_input(self, user_msg: str) -> dict:
        return {"messages": [HumanMessage(content=user_msg)]}

    def chat(self, user_msg: str):
        return self.agent.invoke(self.format_input(user_msg), config=self.config)

    def stream(self, user_msg: str):
        result = self.agent.stream(
            input=self.format_input(user_msg),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        stopwatch = Stopwatch()
        first_token_seen = False
        try:
            for chunk in result:
                if CheckUserBargeIn():
                    break

                if chunk.get("type", None) == "messages":
                    token, metadata = chunk.get("data", None)
                    if isinstance(token, AIMessageChunk) and isinstance(token.content, str):
                        if not first_token_seen and token.content:
                            first_token_seen = True
                            latency_tracker.record(
                                Metric.LLM_FIRST_TOKEN, stopwatch.elapsed_ms()
                            )
                        yield token.content

        except Exception as e:
            logger.exception("chat stream failed")
            yield ("content", f"Got an error: {e}")
        finally:
            latency_tracker.record(Metric.LLM_STREAM, stopwatch.elapsed_ms())