"""
Skills — reusable procedures the agent can load, including ones it wrote.

This is the half of Hermes that most distinguishes it: a skill is a markdown
procedure the agent can write for itself when it solves something novel, and
reload next time. The list is read from disk; installing and removing goes
through the CLI so the catalogue and its safety checks apply.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from pathlib import Path

from ... import platforms
from .. import widgets as w
from ..shell import Page


class SkillsPage(Page):
    title = "Skills"
    group = "Agent"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        header = w.PageHeader(
            "Agent", "Skills",
            "Procedures the agent can load on demand. Hermes writes its own "
            "when it solves something new, and reuses them later.")
        self._count = w.label("", "Faint")
        header.add_action(self._count)
        layout.addWidget(header)

        install = w.Card("Install")
        self._name = QLineEdit()
        self._name.setPlaceholderText("Catalogue name, owner/repo, or a git URL")
        install.add(w.row(self._name, w.button("Install", "Primary", self._install),
                          stretch_last=False))
        install.add(w.label(
            "Hermes audits a skill before installing it and refuses one it "
            "judges dangerous. Installing runs its checks, not ours.",
            "Faint", wrap=True))
        layout.addWidget(install)

        self._list_card = w.Card("Installed")
        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(2)
        self._list_card.add_layout(self._list_box)
        layout.addWidget(self._list_card)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    def refresh(self) -> None:
        self.jobs.run(self.hermes.skills, self._show,
                      lambda e: self._message.setText(e))

    def _show(self, skills: list[dict]) -> None:
        while self._list_box.count():
            item = self._list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._count.setText(f"{len(skills)} installed")
        if not skills:
            self._list_box.addWidget(w.label(
                "No skills yet. The bundled set arrives with an install.", "Faint"))
            return
        for skill in skills:
            name = w.label(skill["name"], "body_bold")
            name.setFixedWidth(230)
            description = w.label(
                (skill.get("description") or "").strip()[:150] or "no description",
                "Faint", wrap=True)
            reveal = w.button("Reveal", "Quiet",
                              lambda p=skill["path"]: platforms.reveal(Path(p)))
            self._list_box.addWidget(w.row(name, description, w.spacer(), reveal,
                                           stretch_last=False))

    def _install(self) -> None:
        name = self._name.text().strip()
        if not name:
            return
        self._message.setText(f"Installing {name}…")
        self.jobs.run(
            lambda: self.hermes.run(["skills", "install", name], timeout=300),
            self._after, lambda e: self._message.setText(e))

    def _after(self, result) -> None:
        self._message.setText("Installed." if result.ok else result.message)
        self._name.clear()
        self.refresh()
