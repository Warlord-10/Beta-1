"""Tool: ask_user — pause the task and ask the user a question.

The tool raises a LangGraph ``interrupt``: the run stops, the pipeline shows
the question (TUI + voice) and routes the user's next message back as the
answer, then the run resumes with that answer as this tool's result.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_user(question: str, options: list[str]) -> str:
    """Ask the user a question and wait for the answer. The task stays paused
    until they reply.

    Use it only when you are blocked on something only the user can provide:
    missing information, a choice with real consequences, or approval of your
    plan. Never ask for something you can find out yourself.

    Args:
        question: One clear question. For plan approval, include the plan
            as numbered steps.
        options: 2-4 short answers the user can pick from. They can always
            reply in their own words instead.

    Returns:
        The user's answer: one of the options, or their own text.
    """
    return interrupt({"question": question, "options": options})
