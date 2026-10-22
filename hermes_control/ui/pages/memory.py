"""
Memory — what the agent carries between sessions.

Hermes keeps two curated files and injects both into every system prompt, each
under a character budget set in config. They are the agent's long-term notes,
so they are worth reading occasionally: a wrong fact here is repeated in every
future conversation.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .. import widgets as w
from ..shell import Page
from ._fileedit import FileEditorPage


class _Agent(FileEditorPage):
    title = "Memory"
    group = "Agent"
    filename = "memories/MEMORY.md"
    intro = "Facts the agent has chosen to keep."


class _User(FileEditorPage):
    title = "Memory"
    group = "Agent"
    filename = "memories/USER.md"
    intro = "What the agent believes about you."


class MemoryPage(Page):
    title = "Memory"
    group = "Agent"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        layout = QVBoxLayout(self)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(14)
        layout.addWidget(w.PageHeader(
            "Agent", "Memory",
            "Two curated files, injected into every system prompt under the "
            "character budgets set in Config. A wrong fact here is repeated "
            "in every future conversation."))
        self._budget = w.label("", "Faint", wrap=True)
        layout.addWidget(self._budget)
        self._tabs = QTabWidget()
        self._agent = _Agent(app)
        self._user = _User(app)
        self._tabs.addTab(self._agent, "Agent memory")
        self._tabs.addTab(self._user, "About you")
        layout.addWidget(self._tabs, 1)

    def refresh(self) -> None:
        self._agent.refresh()
        self._user.refresh()
        config = self.hermes.read_config().get("memory", {}) or {}
        enabled = config.get("memory_enabled", True)
        self._budget.setText(
            f"Memory is {'on' if enabled else 'off'} · agent budget "
            f"{config.get('memory_char_limit', 2200)} characters · profile budget "
            f"{config.get('user_char_limit', 1375)} characters")
