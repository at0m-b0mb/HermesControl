"""
A page that is one editable file.

Hermes keeps several of the agent's most important inputs as plain markdown on
disk — its identity, its curated memory, what it knows about you. Those want
an editor, not a form, so three pages share this one.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from .. import widgets as w
from ..shell import Page


class FileEditorPage(Page):
    """Edit one file, with its own explanation and a save that reports."""

    filename = ""
    intro = ""
    placeholder = ""

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._path: Path | None = None
        self._loaded = ""

        layout = QVBoxLayout(self)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(14)

        header = w.PageHeader(self.group, self.title, self.intro)
        self._path_label = w.label("", "MonoFaint")
        header.add_action(self._path_label)
        layout.addWidget(header)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MonoEdit")
        self._editor.setPlaceholderText(self.placeholder)
        self._editor.textChanged.connect(self._touched)
        layout.addWidget(self._editor, 1)

        self._message = w.label("", "Faint", wrap=True)
        self._save = w.button("Save", "Primary", self.save)
        self._save.setEnabled(False)
        self._reload = w.button("Reload", "", self.refresh)
        layout.addWidget(w.row(self._message, w.spacer(), self._reload, self._save))

    def target(self) -> Path:
        return self.hermes.home / self.filename

    def refresh(self) -> None:
        path = self.target()
        self._path = path
        self._path_label.setText(str(path))
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError as exc:
            self._message.setText(f"Cannot read {path}: {exc}")
            return
        self._loaded = text
        self._editor.blockSignals(True)
        self._editor.setPlainText(text)
        self._editor.blockSignals(False)
        self._save.setEnabled(False)
        self._message.setText(
            f"{len(text.splitlines())} lines" if text
            else "Does not exist yet; saving will create it.")

    def _touched(self) -> None:
        dirty = self._editor.toPlainText() != self._loaded
        self._save.setEnabled(dirty)
        if dirty:
            self._message.setText("Unsaved changes.")

    def save(self) -> None:
        path = self._path or self.target()
        text = self._editor.toPlainText()

        def work():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                backup = path.with_suffix(path.suffix + ".bak")
                backup.write_bytes(path.read_bytes())
            path.write_text(text, encoding="utf-8")
            return path

        def done(written):
            self._loaded = text
            self._save.setEnabled(False)
            self._message.setText(f"Saved {written}. Previous kept as .bak")

        self.jobs.run(work, done,
                      lambda e: self._message.setText(f"Could not save: {e}"))
