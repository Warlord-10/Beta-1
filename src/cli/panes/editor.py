"""Editor pane — a small filesystem browser + text editor.

Defaults the tree to ``$HOME`` so the user is not boxed into the project
directory. The toolbar lets them re-root to any path, save with the button
or with Ctrl+S, and reload the file from disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, DirectoryTree, Input, Static, TextArea


_LANGS = {
    ".py": "python",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "bash",
    ".html": "html",
    ".css": "css",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
}


class EditorPane(Container):
    """Filesystem tree + editable text area, with save."""

    # Safety cap to avoid stalling the UI on accidental huge-file opens.
    MAX_BYTES = 1024 * 1024

    DEFAULT_ROOT = Path.home()

    BINDINGS = [
        Binding("ctrl+s", "save_file", "Save", show=True),
    ]

    DEFAULT_CSS = """
    EditorPane { padding: 1 2; }
    EditorPane #editor-toolbar { height: auto; padding: 0 0 1 0; }
    EditorPane #editor-toolbar Button { margin-right: 1; }
    EditorPane #editor-toolbar Input  { width: 1fr; }
    EditorPane #editor-toolbar Static { padding: 1 1 0 1; }
    EditorPane #editor-row { height: 1fr; }
    EditorPane DirectoryTree {
        width: 40;
        border-right: solid $primary-darken-2;
    }
    EditorPane #editor-right { width: 1fr; height: 1fr; }
    EditorPane TextArea { height: 1fr; }
    EditorPane #editor-status { padding: 1 1 0 1; color: $text-muted; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._current: Optional[Path] = None
        self._dirty = False
        self._root = self.DEFAULT_ROOT

    # ── layout ───────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static("📝  [bold]Editor[/]", markup=True)

        with Horizontal(id="editor-toolbar"):
            yield Input(
                value=str(self._root),
                placeholder="Tree root (press Enter to apply, e.g. /, ~, /Users/...)",
                id="editor-root",
            )
            yield Button("Save  (Ctrl+S)", id="editor-save", variant="primary")
            yield Button("Reload", id="editor-reload")

        yield Static("[dim]no file open[/]", id="editor-path", markup=True)

        with Horizontal(id="editor-row"):
            yield DirectoryTree(str(self._root), id="editor-tree")
            with Vertical(id="editor-right"):
                yield TextArea.code_editor(
                    "", language=None, show_line_numbers=True,
                    id="editor-textarea",
                )

        yield Static("", id="editor-status", markup=True)

    # ── tree / input events ──────────────────────────────────────────────
    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self._open(Path(event.path))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "editor-root":
            return
        new_root = Path(event.value).expanduser()
        if not new_root.is_dir():
            self._set_status(f"[red]Not a directory:[/] {new_root}")
            return
        self._root = new_root
        # Replace the existing DirectoryTree because changing `path` after
        # mount is not reliably supported across Textual versions.
        old = self.query_one("#editor-tree", DirectoryTree)
        row = self.query_one("#editor-row")
        old.remove()
        row.mount(DirectoryTree(str(new_root), id="editor-tree"), before=0)
        self._set_status(f"[green]Tree rooted at[/] {new_root}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "editor-save":
            self.action_save_file()
        elif event.button.id == "editor-reload":
            if self._current is not None:
                self._open(self._current)

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        if self._current is None:
            return
        self._dirty = True
        self._refresh_status()

    # ── actions ──────────────────────────────────────────────────────────
    def action_save_file(self) -> None:
        if self._current is None:
            self._set_status("[yellow]Open a file from the tree first.[/]")
            return
        text = self.query_one("#editor-textarea", TextArea).text
        try:
            self._current.write_text(text, encoding="utf-8")
        except OSError as e:
            self._set_status(f"[red]Save failed:[/] {e}")
            return
        self._dirty = False
        self._set_status(f"[green]✓ Saved[/] {self._current}")

    # ── file open ────────────────────────────────────────────────────────
    def _open(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            size = path.stat().st_size
        except OSError as e:
            self._set_status(f"[red]Cannot stat:[/] {e}")
            return
        if size > self.MAX_BYTES:
            self._set_status(
                f"[red]File too large[/] ({size} bytes > {self.MAX_BYTES})"
            )
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self._set_status("[red]Binary or non-UTF-8 file — not loaded[/]")
            return
        except OSError as e:
            self._set_status(f"[red]Read failed:[/] {e}")
            return

        ta = self.query_one("#editor-textarea", TextArea)
        try:
            ta.language = _LANGS.get(path.suffix.lower())
        except Exception:
            pass
        ta.load_text(text)

        self._current = path
        self._dirty = False
        self._update_path_label()
        self._set_status(f"[green]Opened[/] {path}")

    # ── status helpers ───────────────────────────────────────────────────
    def _update_path_label(self) -> None:
        label = self.query_one("#editor-path", Static)
        if self._current is None:
            label.update("[dim]no file open[/]")
        else:
            label.update(f"[b]{self._current}[/]")

    def _refresh_status(self) -> None:
        if self._current is None:
            return
        if self._dirty:
            self._set_status("[yellow]●  unsaved changes — press Ctrl+S[/]")
        else:
            self._set_status("[dim]saved[/]")

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#editor-status", Static).update(text)
        except Exception:
            pass
