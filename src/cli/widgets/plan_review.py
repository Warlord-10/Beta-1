"""Small state holder for the human-in-the-loop plan-review flow.

The TUI displays a plan posted by the workflow and routes the user's next
message to `Pipeline.submit_plan_review` instead of the chat agent.
"""

from __future__ import annotations

from typing import Optional


class PlanReview:
    """Tracks whether the TUI is currently awaiting a plan-review verdict."""

    def __init__(self) -> None:
        self._awaiting = False
        self._plan: Optional[dict] = None

    @property
    def awaiting(self) -> bool:
        return self._awaiting

    @property
    def plan(self) -> Optional[dict]:
        return self._plan

    def request(self, plan: dict) -> None:
        self._plan = plan
        self._awaiting = True

    def resolve(self) -> None:
        self._awaiting = False
        self._plan = None

    # ── presentation ─────────────────────────────────────────────────────
    @staticmethod
    def render(plan: dict) -> str:
        plan_md = plan.get("implementation_plan", "") or "(empty plan)"
        checklist = plan.get("action_checklist", []) or []
        body = f"[bold yellow]📋 Plan review requested[/]\n\n{plan_md}\n"
        if checklist:
            body += "\n[b]Checklist:[/]\n" + "\n".join(
                f"  • {item}" for item in checklist
            )
        body += (
            "\n\n[dim]Reply with [b]/approve[/], [b]/reject[/], or any other "
            "text to submit a revised plan.[/]"
        )
        return body
