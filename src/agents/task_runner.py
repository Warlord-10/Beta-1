"""Running a worker agent (beta-large, the web agent) on one task.

A worker run can pause on a question for the user (``ask_user`` or a
permission check). ``run_task`` answers each pause through ``ask`` and
resumes, until the agent gives its final answer.

``ask`` also travels with the run as LangGraph runtime context
(``TaskContext``), so a tool that starts another worker (``web_task``) can
hand it on: that worker's questions reach the user the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from langgraph.types import Command

# Asks the user a question with options and returns their answer.
AskUser = Callable[[str, list[str]], Awaitable[str]]

# Answer given to every question when nobody can respond.
NO_USER_ANSWER = "The user is not available. Don't do this; continue without it or stop and report."


async def no_user(question: str, options: list[str]) -> str:
    return NO_USER_ANSWER


@dataclass
class TaskContext:
    ask: AskUser


async def run_task(agent, task_input: dict, config: dict, ask: AskUser) -> str:
    """Run ``agent`` to completion, answering every pause via ``ask``. Returns the final answer."""
    context = TaskContext(ask=ask)
    result = await agent.ainvoke(task_input, config=config, context=context)
    while interrupts := result.get("__interrupt__"):
        answers = {i.id: await ask(i.value["question"], i.value["options"]) for i in interrupts}
        result = await agent.ainvoke(Command(resume=answers), config=config, context=context)
    return result["messages"][-1].text
