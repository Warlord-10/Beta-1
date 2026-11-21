"""Web Agent — does web work for beta-large in its own context.

Beta-large calls the ``web_task`` tool with a brief. The web agent searches,
reads pages and drives a text-only browser on its own thread, then returns its findings with sources as
the tool's result. Beta-large never sees the pages it read, only the answer.
"""

from __future__ import annotations

from functools import cache

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ToolRetryMiddleware,
)
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from src.agents.task_runner import AskUser, TaskContext, no_user, run_task
from src.config.context import environment_context
from src.config.logger import get_logger
from src.llms import llm_factory
from src.prompts import load_prompt
from src.tools.browser_tools import BROWSER_TOOLS
from src.tools.search_tools import advanced_search, extract_text, regular_search
from src.tools.user_tools import ask_user

logger = get_logger("agents.web")

# Each tool call is two graph steps; browser tasks take many small steps.
_RECURSION_LIMIT = 100

# Pages are big: past _CLEAR_TOOLS_AT tokens, all but the latest
# _KEEP_TOOL_RESULTS tool outputs are hidden from the model.
_CLEAR_TOOLS_AT = 15_000
_KEEP_TOOL_RESULTS = 2

SEARCH_TOOLS = [regular_search, advanced_search, extract_text]
WEB_TOOLS = [*SEARCH_TOOLS, *BROWSER_TOOLS, ask_user]


def search_errors_as_results() -> ToolRetryMiddleware:
    """A failed search ("No results found.", a network error) becomes an error
    result the model can react to, instead of crashing the run. Limited to the
    search tools: ask_user pauses the run by raising, which must pass through."""
    return ToolRetryMiddleware(tools=SEARCH_TOOLS, max_retries=1, on_failure="continue")


class WebAgent:
    def __init__(self):
        self.llm = llm_factory.create(
            "GEMINI_3_5_FLASH_LITE", temperature=0, max_tokens=4096, thinking_level="low"
        )
        self.agent = create_agent(
            model=self.llm,
            tools=WEB_TOOLS,
            system_prompt=f"{load_prompt('web_agent')}\n\n{environment_context()}",
            checkpointer=InMemorySaver(),
            context_schema=TaskContext,
            middleware=[
                search_errors_as_results(),
                ContextEditingMiddleware(edits=[ClearToolUsesEdit(
                    trigger=_CLEAR_TOOLS_AT,
                    keep=_KEEP_TOOL_RESULTS,
                    exclude_tools=("ask_user",),
                )]),
            ],
        )

    async def arun(self, task: str, task_id: str, ask: AskUser) -> str:
        """Do one web task on its own thread and return the findings."""
        config = {
            "configurable": {"thread_id": f"web-{task_id}"},
            "recursion_limit": _RECURSION_LIMIT,
        }
        return await run_task(self.agent, {"messages": [HumanMessage(task)]}, config, ask)


@cache
def _web_agent() -> WebAgent:
    return WebAgent()


@tool
async def web_task(task: str, runtime: ToolRuntime[TaskContext]) -> str:
    """Hand a web job to the web agent and get back its findings with sources.

    Use it for anything that needs more than one quick search: researching
    a topic, comparing options, reading several pages, or doing things on a
    website (searching a site, filling forms, adding to a cart, checking an
    account; the user logs in when needed). The web agent works in its own
    context, so its page reads don't fill yours.

    Args:
        task: A self-contained brief: what to find or do, any constraints,
            and what the answer should contain. It can't see your
            conversation, so include every detail it needs.

    Returns:
        The web agent's findings, with the URLs they came from.
    """
    ask = runtime.context.ask if runtime.context else no_user
    logger.info("Web task %s: %s", runtime.tool_call_id, task[:120])
    try:
        return await _web_agent().arun(task, runtime.tool_call_id, ask)
    except GraphRecursionError:
        return "The web agent ran out of steps before finishing. Try a narrower brief."
    except Exception as exc:
        logger.exception("web task failed")
        return f"The web agent failed: {exc}"
