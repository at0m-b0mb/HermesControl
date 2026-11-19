"""
Skills — reusable procedures the agent can load, including ones it wrote.

This is the half of Hermes that most distinguishes it: a skill is a markdown
procedure the agent can write for itself when it solves something novel, and
reload next time. The list is read from disk; installing and removing goes
through the CLI so the catalogue and its safety checks apply.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit,
                               QTextEdit, QVBoxLayout, QWidget)

from pathlib import Path

from ... import hub
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

        # --- mail ----------------------------------------------------------
        # First, because it is the question this page exists to answer. The
        # Gateway page's email form lets people write *to* the agent; this
        # is the other direction, and nothing in the app said so before.
        mail = w.Card("Give the agent your mailbox", accent=True)
        mail.add(w.label(
            "The email settings on the Gateway page work one way: people "
            "write to the agent and it replies. Letting the agent read, "
            "search and send from your own Gmail or Outlook is a skill, "
            "installed from here. It is not a connector and not an MCP "
            "server, which is why looking in either of those and finding "
            "nothing is so easy to do.", "Faint", wrap=True))
        self._mail_box = QVBoxLayout()
        self._mail_box.setSpacing(4)
        mail.add_layout(self._mail_box)
        layout.addWidget(mail)

        # --- the hub ---------------------------------------------------------
        search = w.Card("Find a skill")
        search.add(w.label(
            "Searches skills.sh, ClawHub, GitHub and a dozen provider "
            "registries at once. This is Hermes's largest extension "
            "surface by a wide margin — far bigger than the connector list "
            "or the MCP catalogue.", "Faint", wrap=True))
        self._query = QLineEdit()
        self._query.setPlaceholderText("email, calendar, github, pdf…")
        self._query.returnPressed.connect(self._search)
        self._source = QComboBox()
        self._source.addItems(list(hub.SOURCES))
        self._source.setFixedWidth(140)
        self._search_button = w.button("Search", "Primary", self._search)
        search.add(w.row(self._query, self._source, self._search_button,
                         stretch_last=False))
        starters = QWidget()
        starter_line = QHBoxLayout(starters)
        starter_line.setContentsMargins(0, 0, 0, 0)
        starter_line.setSpacing(6)
        starter_line.addWidget(w.label("Try", "Faint"))
        for word, hint in hub.STARTERS:
            chip = w.button(word, "Quiet", lambda q=word: self._search(q))
            chip.setToolTip(hint)
            starter_line.addWidget(chip)
        starter_line.addStretch(1)
        search.add(starters)
        self._results_box = QVBoxLayout()
        self._results_box.setSpacing(2)
        search.add_layout(self._results_box)
        self._search_status = w.label("", "Faint", wrap=True)
        search.add(self._search_status)
        layout.addWidget(search)

        # What a skill actually says, before it is installed. A skill is a
        # procedure the agent follows and may carry scripts it runs, so
        # reading one first is the point rather than a nicety.
        self._preview = w.Card("Preview")
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setMinimumHeight(220)
        self._preview_text.setProperty("role", "Mono")
        self._preview.add(self._preview_text)
        self._preview.setVisible(False)
        layout.addWidget(self._preview)

        install = w.Card("Install by name")
        self._name = QLineEdit()
        self._name.setPlaceholderText("Identifier, owner/repo, or a SKILL.md URL")
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
        self._show_mail(skills)
        broken = [s for s in skills if s.get("missing")]
        self._count.setText(f"{len(skills)} installed")
        if not skills:
            self._list_box.addWidget(w.label(
                "No skills yet. The bundled set arrives with an install.", "Faint"))
            return
        if broken:
            # These install cleanly, list normally, and fail the first time
            # the agent reaches for them. Nothing else says so.
            self._list_box.addWidget(w.label(
                f"{len(broken)} skill(s) cannot run: each needs a command "
                f"that is not on this machine. They will fail the first "
                f"time the agent uses them, with an error that does not "
                f"obviously point here.", "Faint", wrap=True))
        for skill in skills:
            name = w.label(skill["name"], "body_bold")
            name.setFixedWidth(206)
            where = w.label(skill.get("category") or "top level", "MonoFaint")
            where.setFixedWidth(120)
            missing = skill.get("missing") or []
            badge = w.Badge(f"NEEDS {missing[0].upper()}" if missing else "READY",
                            "fault" if missing else "live")
            badge.setFixedWidth(128)
            badge.apply_mode(self.app.mode)
            if missing:
                badge.setToolTip(
                    f"Install {', '.join(missing)} and this skill works. "
                    f"Until then the agent will try it and fail.")
            description = w.label(
                (skill.get("description") or "").strip()[:150] or "no description",
                "Faint", wrap=True)
            description.setMinimumWidth(1)
            reveal = w.button("Reveal", "Quiet",
                              lambda p=skill["path"]: platforms.reveal(Path(p)))
            reveal.setFixedWidth(84)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for widget in (name, where, badge):
                line.addWidget(widget)
            line.addWidget(description, 1)
            line.addWidget(reveal)
            self._list_box.addWidget(holder)

    def _show_mail(self, skills: list[dict]) -> None:
        """Say which of the three mail routes is already in place.

        The himalaya *skill* ships with Hermes while the himalaya
        *binary* does not, so the honest row here is neither "install
        this" nor "ready" but "you have it, and it cannot run yet" —
        with the one command that fixes it.
        """
        self._clear(self._mail_box)
        by_name = {s["name"]: s for s in skills}
        for route in hub.MAIL_ROUTES:
            have = by_name.get(route.skill)
            missing = list(have.get("missing") or []) if have else []
            title = w.label(route.what, "body_bold")
            title.setFixedWidth(282)
            if have and not missing:
                badge, token = "READY", "live"
                # Ready means the skill and its command are both here. It
                # does not mean an account is connected, and claiming so
                # would be the exact kind of false green this app exists
                # to avoid.
                detail = (f"{route.needs} {route.setup_note}"
                          if route.setup_note else route.needs)
                action = None
                if route.setup:
                    action = w.button(
                        "Connect", "Primary",
                        lambda r=route: self._connect_mail(r))
                    action.setFixedWidth(96)
            elif have:
                badge, token = "NEEDS " + missing[0].upper(), "fault"
                detail = (f"The skill is installed, but {missing[0]} is not "
                          f"on this machine, so the agent will try it and "
                          f"fail. Install it with: {route.get}"
                          if route.get else
                          f"The skill is installed but {missing[0]} is "
                          f"missing, so it cannot run.")
                action = None
            else:
                badge, token = "NOT INSTALLED", "idle"
                detail = route.needs
                action = w.button(
                    "Install", "",
                    lambda i=route.identifier: self._install_id(i))
                action.setFixedWidth(96)
            mark = w.Badge(badge, token)
            mark.setFixedWidth(146)
            mark.apply_mode(self.app.mode)
            text = w.label(detail, "Faint", wrap=True)
            text.setMinimumWidth(1)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            line.addWidget(title)
            line.addWidget(mark)
            line.addWidget(text, 1)
            if action is not None:
                line.addWidget(action)
            else:
                line.addSpacing(104)
            self._mail_box.addWidget(holder)

    def _connect_mail(self, route) -> None:
        """Hand an account wizard to a real terminal.

        It asks questions and writes a password to the system keyring,
        neither of which can happen in a captured subprocess.
        """
        ok, detail = platforms.open_shell(route.setup)
        self._message.setText(
            f"{detail} Answer its questions there, then come back. "
            f"If nothing opened, run: {route.setup}"
            if ok else f"{detail} Run this yourself: {route.setup}")

    # --- the hub ------------------------------------------------------------

    def _search(self, query: str = "") -> None:
        text = (query or self._query.text()).strip()
        if not text:
            return
        self._query.setText(text)
        self._search_button.setEnabled(False)
        self._search_status.setText(f"Searching every registry for {text}…")
        source = self._source.currentText()
        self.jobs.run(
            lambda: self.hermes.skills_search(text, source),
            self._show_results,
            lambda e: (self._search_button.setEnabled(True),
                       self._search_status.setText(e)))

    def _show_results(self, outcome: tuple[bool, str]) -> None:
        self._search_button.setEnabled(True)
        ok, payload = outcome
        self._clear(self._results_box)
        if not ok:
            self._search_status.setText(f"Search failed: {payload}")
            return
        found = hub.rank(hub.parse_search(payload))
        if not found:
            self._search_status.setText(
                "Nothing matched. Try a plainer word — the registries index "
                "by what a skill is called, not by what it does.")
            return
        self._search_status.setText(
            f"{len(found)} result(s), official and verified first. A "
            f"community skill is someone else's procedure: read it before "
            f"you install it.")
        for skill in found:
            name = w.label(skill.name, "body_bold")
            name.setFixedWidth(170)
            badge = w.Badge(skill.trust.upper() or "UNRATED",
                            "live" if skill.official else "idle")
            badge.setFixedWidth(104)
            badge.apply_mode(self.app.mode)
            detail = w.label(skill.description or "no description", "Faint",
                             wrap=True)
            detail.setMinimumWidth(1)
            detail.setToolTip(f"{skill.identifier}  ·  {skill.source}")
            read = w.button("Read", "Quiet",
                            lambda i=skill.identifier: self._inspect(i))
            read.setFixedWidth(76)
            add = w.button("Install", "",
                           lambda i=skill.identifier: self._install_id(i))
            add.setFixedWidth(88)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            line.addWidget(name)
            line.addWidget(badge)
            line.addWidget(detail, 1)
            line.addWidget(read)
            line.addWidget(add)
            self._results_box.addWidget(holder)

    def _inspect(self, identifier: str) -> None:
        self._preview.setVisible(True)
        self._preview_text.setPlainText(f"Reading {identifier}…")
        self.jobs.run(
            lambda: self.hermes.skills_inspect(identifier),
            lambda r: self._preview_text.setPlainText(
                (r.stdout or r.stderr or "").strip()
                or "Hermes returned nothing for this skill."),
            lambda e: self._preview_text.setPlainText(e))

    def _install_id(self, identifier: str) -> None:
        self._message.setText(f"Installing {identifier}…")
        self.jobs.run(lambda: self.hermes.skills_install(identifier),
                      self._after, lambda e: self._message.setText(e))

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _install(self) -> None:
        name = self._name.text().strip()
        if not name:
            return
        self._install_id(name)

    def _after(self, result) -> None:
        if result.ok:
            self._message.setText("Installed. It is available to the agent "
                                  "from the next turn.")
        else:
            # Hermes's refusal says which check failed and why, and that is
            # the useful part — "install failed" is not.
            self._message.setText(
                (result.stderr or result.stdout or "").strip()
                or result.message)
        self._name.clear()
        self.refresh()
