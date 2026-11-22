"""ContextBar — how full the chat agent's context window is."""

from __future__ import annotations

from textual.widgets import Static

_WIDTH = 20


GREEN, ORANGE, RED = "#4caf50", "#ff9800", "#f44336"


def _color(used: float) -> str:
    if used < 0.7:
        return GREEN
    return ORANGE if used < 0.9 else RED


class ContextBar(Static):
    DEFAULT_CSS = """
    ContextBar {
        dock: right;
        height: 1;
        width: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="context-bar")

    def show(self, tokens: int, window: int) -> None:
        used = tokens / window if window else 0.0
        filled = min(_WIDTH, round(used * _WIDTH))
        self.update(
            f"[dim]context {tokens / 1000:.1f}k/{window / 1000:.0f}k[/] "
            f"[{_color(used)}]{'━' * filled}[/][dim]{'─' * (_WIDTH - filled)}[/] "
            f"[{_color(used)}]{used:.0%}[/]"
        )


if __name__ == "__main__":
    assert (_color(0.5), _color(0.7), _color(0.89), _color(0.9), _color(1.3)) == (
        GREEN, ORANGE, ORANGE, RED, RED
    )
    print("context_bar ok")
