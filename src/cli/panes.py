from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import (
    Checkbox,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Switch,
)


class SettingsPane(Container):
    DEFAULT_CSS = """
    SettingsPane { padding: 2 3; }
    SettingsPane .row { height: auto; width: 100%; margin-bottom: 1; }
    SettingsPane Label.label {
        width: 30%;
        content-align: left middle;
        padding: 1 0;
    }
    SettingsPane Input, SettingsPane Switch { width: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("⚙️  [bold]Settings[/]\n\nCustomize your experience.\n", markup=True)
        with Horizontal(classes="row"):
            yield Label("Display name:", classes="label")
            yield Input(value="Claude User", id="setting-name")
        with Horizontal(classes="row"):
            yield Label("Dark mode:", classes="label")
            yield Switch(value=True, id="setting-dark")
        with Horizontal(classes="row"):
            yield Label("Notifications:", classes="label")
            yield Switch(value=True, id="setting-notif")
        with Horizontal(classes="row"):
            yield Label("Model:", classes="label")
            yield Input(value="claude-opus-4.7", id="setting-model")


class SchedulesPane(Container):
    DEFAULT_CSS = """
    SchedulesPane { padding: 2 3; }
    SchedulesPane DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📅  [bold]Schedules[/]\n", markup=True)
        yield DataTable(id="schedules-table", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Time", "Title", "Repeat", "Status")
        rows = [
            ("09:00", "Morning briefing", "Daily", "✅ Active"),
            ("12:30", "Team standup", "Mon–Fri", "✅ Active"),
            ("18:00", "Email summary", "Daily", "⏸️  Paused"),
            ("Sun 20:00", "Weekly review", "Weekly", "✅ Active"),
        ]
        for row in rows:
            t.add_row(*row)


class TasksPane(Container):
    DEFAULT_CSS = """
    TasksPane { padding: 2 3; }
    TasksPane Checkbox { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("✅  [bold]Tasks[/]\n", markup=True)
        yield Checkbox("Finish writing the Textual GUI demo", value=True)
        yield Checkbox("Review pull request #428", value=False)
        yield Checkbox("Call the dentist", value=False)
        yield Checkbox("Prepare slides for Friday's demo", value=False)
        yield Checkbox("Read chapter 4 of 'Designing ML Systems'", value=False)


class SessionsPane(Container):
    DEFAULT_CSS = """
    SessionsPane { padding: 2 3; }
    SessionsPane ListView { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("🗂️  [bold]Sessions[/]\n", markup=True)
        yield ListView(
            ListItem(
                Static("● [b]Planning Q3 roadmap[/]   [dim](2h ago · 42 messages)[/]")
            ),
            ListItem(
                Static(
                    "○ [b]Debug the payment service[/]   [dim](yesterday · 17 messages)[/]"
                )
            ),
            ListItem(
                Static(
                    "○ [b]Weekend trip brainstorm[/]   [dim](3 days ago · 8 messages)[/]"
                )
            ),
            ListItem(
                Static("○ [b]Resume review[/]   [dim](last week · 23 messages)[/]")
            ),
        )


class ContextsPane(Container):
    DEFAULT_CSS = """
    ContextsPane { padding: 2 3; }
    """

    def compose(self) -> ComposeResult:
        yield Static("📚  [bold]Loaded Contexts[/]\n", markup=True)
        yield Static(
            "• [green]●[/] [b]project-spec.md[/]      [dim]1.2k tokens[/]\n"
            "• [green]●[/] [b]api-reference.pdf[/]    [dim]8.4k tokens[/]\n"
            "• [yellow]●[/] [b]meeting-notes.txt[/]   [dim]0.6k tokens[/]\n"
            "• [dim]○[/]  [b]old-design.md[/]          [dim]unloaded[/]\n\n"
            "[dim]Total active context: 10.2k / 200k tokens[/]",
            markup=True,
        )
