from __future__ import annotations

import uuid
from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware import after_model
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.messages import messages_to_dict
from langchain_core.messages.utils import count_tokens_approximately
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from src.config.context import environment_context
from src.config.event_bus import EVENT_BUS, ToolCall
from src.config.global_events import *
from src.config.global_queues import *
from src.config.logger import get_logger
from src.config.settings import SETTINGS
from src.config.workflow_context import cancel_workflow, get_workflow_status
from src.llms import llm_factory
from src.llms.factory import is_timeout
from src.observability import Metric, Stopwatch, latency_tracker
from src.prompts import load_prompt
from src.states.main_state import ChatState
from src.utils.transcript import Transcript

# Read-only file tools
from src.tools.file_tools import (
    get_file_info,
    list_directory,
    read_file,
    search_content,
    search_files,
)

# Memory tools
from src.tools.memory_tools.daily_memory_tools import (
    add_to_daily_memory,
    read_daily_memory,
    memory_path,
)

# Scheduler tools
from src.tools.scheduler_tools import (
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task,
)

# Web search (lightweight — deep research goes through delegate_to_planner)
from src.tools.search_tools import regular_search

# Skills (read-only: list and load)
from src.tools.skill_tools.skill_tool import SKILL_READ_TOOLS

# Safe system tools
from src.tools.system_tools.safe_bash import safe_bash

logger = get_logger("agents.chat_agent")


# Recent chat turns attached to every delegated task.
_EXCERPT_TURNS = 10


def _conversation_excerpt(messages: list) -> str:
    """Last few user/assistant turns as plain text (tool calls/results skipped)."""
    lines = []
    for msg in messages:
        if msg.type in ("human", "ai") and msg.text.strip():
            who = "User" if msg.type == "human" else "Assistant"
            lines.append(f"{who}: {msg.text.strip()}")
    return "\n".join(lines[-_EXCERPT_TURNS * 2 :]) or "(no prior conversation)"


def _read_memory() -> str:
    try:
        with open(memory_path, "r") as f:
            return f.read().strip() or "(empty)"
    except FileNotFoundError:
        return "(empty)"


@tool
def delegate_to_planner(task_summary: str, runtime: ToolRuntime) -> str:
    """Delegate a complex task to the background autonomous agent.

    Args:
        task_summary: A self-contained brief for the agent — the goal, any
            constraints, relevant paths/names, and what "done" looks like.
            Resolve references like "that file" into concrete names; the
            recent conversation is attached automatically.
    Returns:
        Confirmation with the task id.
    """
    task_id = uuid.uuid4().hex[:8]
    task = (
        f"# Task {task_id}\n{task_summary}\n\n"
        f"## Recent conversation (for context)\n"
        f"{_conversation_excerpt(runtime.state['messages'])}\n\n"
        f"## What I know about the user\n{_read_memory()}"
    )
    ComplexTaskQueue.put((task_id, task))
    logger.info("Task %s delegated: %s", task_id, task_summary)

    return f"""Task {task_id} has been delegated, final update will be provided once it is completed.
    Tell the user that you will update him once this task is completed.
    """


@after_model
def _publish_tool_calls(state, runtime) -> None:
    """Tell the UI which tools the model just decided to call."""
    for call in state["messages"][-1].tool_calls:
        EVENT_BUS.publish(ToolCall(call["name"], call["args"]))


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
    get_workflow_status,
    cancel_workflow,
    # Scheduler
    create_scheduled_task,
    delete_scheduled_task,
    list_scheduled_tasks,
    modify_scheduled_task,
    toggle_scheduled_task,
    # Memory
    add_to_daily_memory,
    read_daily_memory,
    # Skills (read-only)
    *SKILL_READ_TOOLS,
]


# Compaction keeps the last few user turns verbatim and summarises the rest.
# ponytail: fixed count; if the kept turns alone exceed the window (huge tool
# output), compaction re-runs every turn — trim tool results then.
_KEEP_TURNS = 2

_SUMMARY_PROMPT = """You compact the conversation history of a voice assistant.
Write a concise summary that lets the assistant continue seamlessly. Keep:
- facts the user shared about themselves, people, and preferences
- requests made and how they were answered or resolved
- delegated background tasks (with task ids) and their status/outcome
- anything still pending or promised to the user
Drop greetings, chit-chat, and raw tool output. Plain text, no preamble."""


def _conversation_text(messages: list) -> str:
    """Messages as plain text for the summariser; tool output is truncated."""
    lines = []
    for msg in messages:
        if msg.type == "human":
            lines.append(f"User: {msg.text}")
        elif msg.type == "ai":
            if msg.text.strip():
                lines.append(f"Assistant: {msg.text}")
            for call in msg.tool_calls:
                lines.append(f"Assistant called {call['name']}({call['args']})")
        elif msg.type == "tool":
            lines.append(f"Tool {msg.name} returned: {msg.text[:500]}")
    return "\n".join(lines)


class ChatAgent:
    def __init__(self, config: dict):
        self.config = config
        self.checkpointer = InMemorySaver()
        # One attempt only: SDK retries back off silently (up to a minute)
        # while the user waits in silence. Fail fast and say so instead.
        self.llm = llm_factory.create("GEMINI_3_1_FLASH_LITE", temperature=1, max_tokens=256, max_retries=1)
        # Not Gemma: its free tier allows 16k input tokens/minute, the same as
        # CHAT_CONTEXT_WINDOW, so summarising a full context always hit 429.
        self.summary_llm = llm_factory.create("GEMINI_3_1_FLASH_LITE", temperature=0, max_tokens=1024*2)

        # Today's conversation is persisted to chats/<date>/beta_1.jsonl and
        # restored on startup. `_seed` holds messages to prepend to the next
        # input (restored or compacted context); `_saved` counts the messages
        # in the current thread's state that are already in the transcript.
        self.transcript = Transcript("beta_1")
        self._seed, self.context_tokens, self.day_tokens = self.transcript.restore()
        self._saved = len(self._seed)
        self._day = date.today()

        self.agent = create_agent(
            model=self.llm,
            tools=CHAT_AGENT_TOOLS,
            system_prompt=f"{load_prompt('chat_agent')}\n\n{environment_context()}",
            checkpointer=self.checkpointer,
            state_schema=ChatState,
            middleware=[_publish_tool_calls],
        )

    def change_llm(self, new_llm):
        self.agent = create_agent(
            model=new_llm,
            tools=CHAT_AGENT_TOOLS,
            system_prompt=f"{load_prompt('chat_agent')}\n\n{environment_context()}",
            checkpointer=self.checkpointer,
            state_schema=ChatState,
            middleware=[_publish_tool_calls],
        )

    def format_input(self, user_msg: str) -> dict:
        return {"messages": [*self._seed, HumanMessage(content=user_msg)]}

    async def end_turn(self) -> None:
        """Persist the turn, update token counts, and compact if over the window."""
        state = await self.agent.aget_state(self.config)
        messages = state.values.get("messages", [])
        if not messages:
            return  # turn failed before reaching the graph; keep the seed
        self._seed = []

        new = messages[self._saved :]
        self.transcript.add_messages(new)
        self._saved = len(messages)

        if date.today() != self._day:
            self._day, self.day_tokens = date.today(), 0

        # Real usage from the model: the last call's input already covers the
        # system prompt, tool schemas, history and tool results.
        calls = [m for m in new if m.type == "ai" and m.usage_metadata]
        self.day_tokens += sum(m.usage_metadata["total_tokens"] for m in calls)
        if calls:
            self.context_tokens = calls[-1].usage_metadata["total_tokens"]
        else:
            # No model reply (failed/interrupted turn): estimate what was added.
            self.context_tokens += count_tokens_approximately(new)
        self.transcript.append(
            {
                "type": "turn",
                "context_tokens": self.context_tokens,
                "day_tokens": self.day_tokens,
            }
        )

        if self.context_tokens > SETTINGS.CHAT_CONTEXT_WINDOW:
            await self._compact(messages)

    async def _compact(self, messages: list) -> None:
        human_idx = [i for i, m in enumerate(messages) if m.type == "human"]
        if len(human_idx) <= _KEEP_TURNS:
            return
        cut = human_idx[-_KEEP_TURNS]
        old, kept = messages[:cut], messages[cut:]

        summary = await self.summary_llm.ainvoke(
            [SystemMessage(_SUMMARY_PROMPT), HumanMessage(_conversation_text(old))]
        )
        self._seed = [
            HumanMessage(f"[Summary of the earlier conversation today]\n{summary.text}"),
            *kept,
        ]
        # Fresh thread: the next turn starts from summary + kept messages.
        self.config["configurable"]["thread_id"] = str(uuid.uuid4())
        self._saved = len(self._seed)
        self.transcript.append(
            {"type": "compaction", "messages": messages_to_dict(self._seed)}
        )
        logger.info(
            "Compacted chat context: %d tokens, %d messages -> summary + %d kept",
            self.context_tokens, len(messages), len(kept),
        )

    async def async_stream(self, user_msg: str):
        result = self.agent.astream(
            input=self.format_input(user_msg),
            config=self.config,
            stream_mode="messages",
            version="v2",
        )
        stopwatch = Stopwatch()
        first_token_seen = False
        try:
            async for chunk in result:
                if CheckUserBargeIn():
                    break

                if chunk.get("type", None) == "messages":
                    token, metadata = chunk.get("data", None)
                    # .text, not .content: Gemini 3 streams content as a list
                    # of blocks (text + signatures), Gemma as a plain str.
                    if isinstance(token, AIMessageChunk) and (text := token.text):
                        if not first_token_seen:
                            first_token_seen = True
                            latency_tracker.record(
                                Metric.LLM_FIRST_TOKEN, stopwatch.elapsed_ms()
                            )
                        yield text

        except Exception as exc:
            logger.exception("chat stream failed")
            yield "LLM request timed out." if is_timeout(exc) else "LLM is facing some issues."
        finally:
            latency_tracker.record(Metric.LLM_STREAM, stopwatch.elapsed_ms())

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
                    # .text, not .content: Gemini 3 streams content as a list
                    # of blocks (text + signatures), Gemma as a plain str.
                    if isinstance(token, AIMessageChunk) and (text := token.text):
                        if not first_token_seen:
                            first_token_seen = True
                            latency_tracker.record(
                                Metric.LLM_FIRST_TOKEN, stopwatch.elapsed_ms()
                            )
                        yield text

        except Exception as exc:
            logger.exception("chat stream failed")
            yield "LLM request timed out." if is_timeout(exc) else "LLM is facing some issues."
        finally:
            latency_tracker.record(Metric.LLM_STREAM, stopwatch.elapsed_ms())
