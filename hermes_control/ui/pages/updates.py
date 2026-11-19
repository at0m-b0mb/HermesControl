"""
Updates — four different things, four different commands.

The whole reason this page exists separately from Runtime is that the
version numbers on this machine look alike and belong to different
software. Someone reads a version here, concludes Hermes is current, and
has been looking at the control panel's. Every row names what it is a
version *of*, and nothing is drawn as a reassuring tick unless it was
actually checked.
"""

from __future__ import annotations

import subprocess

from PySide6.QtWidgets import QHBoxLayout, QTextEdit, QVBoxLayout, QWidget

from ... import platforms, updates
from ...version_check import latest_release
from .. import widgets as w
from ..shell import Page


class UpdatesPage(Page):
    title = "Updates"
    group = "Installation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._running = False

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        layout.addWidget(w.PageHeader(
            "Installation", "Updates",
            "Four things here update separately. Each row says which one "
            "it is talking about."))

        self._rows_card = w.Card("What is current")
        self._rows = QVBoxLayout()
        self._rows.setSpacing(6)
        self._rows_card.add_layout(self._rows)
        self._rows_card.add(w.row(
            w.button("Check again", "", self.refresh),
            w.button("Show the update plan", "Quiet", self._plan),
            w.spacer()))
        layout.addWidget(self._rows_card)

        self._log_card = w.Card("Output")
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(220)
        self._log.setProperty("role", "Mono")
        self._log_card.add(self._log)
        self._log_card.setVisible(False)
        layout.addWidget(self._log_card)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    # --- reading ------------------------------------------------------------

    def refresh(self) -> None:
        self._message.setText("Checking…")
        self.jobs.run(self._gather, self._show,
                      lambda e: self._message.setText(e))

    def _gather(self) -> list[updates.Available]:
        hermes = self.hermes
        version = hermes.version()
        ok, payload = hermes.update_check()
        agent = updates.parse_hermes_check(payload, version.version, ok)

        skills_ok, skills_payload = hermes.skills_check()
        skills = updates.parse_skills_check(skills_payload, skills_ok)

        # This app. Checked against its own releases rather than assumed
        # current, and reported as "could not tell" when the network says
        # nothing — an update prompt that is wrong costs more than silence.
        from ... import __version__
        tag, error = latest_release()
        app_row = updates.Available(
            "Hermes Control (this app)", installed=__version__,
            latest=tag, command="git -C <this folder> pull")
        if tag:
            app_row.behind = updates.compare_versions(__version__, tag)
            app_row.detail = (
                f"v{tag} is published; this is v{__version__}."
                if app_row.behind else
                f"v{__version__} is the current release.")
        else:
            app_row.detail = (
                f"Could not reach the release list, so whether this is "
                f"current is unknown: {error}")
        return [agent, skills, app_row]

    def _show(self, rows: list[updates.Available]) -> None:
        self._clear(self._rows)
        words = {"behind": ("UPDATE READY", "attention"),
                 "current": ("UP TO DATE", "live"),
                 "unknown": ("UNKNOWN", "idle")}
        behind = 0
        for row in rows:
            name = w.label(row.name, "body_bold")
            name.setFixedWidth(220)
            word, token = words[row.state]
            badge = w.Badge(word, token)
            badge.setFixedWidth(136)
            badge.apply_mode(self.app.mode)
            version = w.label(f"v{row.installed}" if row.installed else "",
                              "MonoFaint")
            version.setFixedWidth(90)
            detail = w.label(row.detail, "Faint", wrap=True)
            detail.setMinimumWidth(1)
            detail.setToolTip(row.command)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for widget in (name, badge, version):
                line.addWidget(widget)
            line.addWidget(detail, 1)
            action = self._action_for(row)
            if action is not None:
                line.addWidget(action)
            else:
                line.addSpacing(126)
            self._rows.addWidget(holder)
            behind += 1 if row.state == "behind" else 0
        self._message.setText(
            f"{behind} thing(s) have an update waiting."
            if behind else
            "Nothing is waiting. Each row was checked just now, against its "
            "own source.")

    def _action_for(self, row: updates.Available):
        if row.state != "behind":
            return None
        if row.name.startswith("Hermes Agent"):
            button = w.button("Update Hermes", "Primary", self._update_agent)
        elif row.name.startswith("Hub skills"):
            button = w.button("Update skills", "Primary", self._update_skills)
        else:
            # This app is a git checkout, and pulling it under a running
            # process would swap the code out from under the window. The
            # honest move is to open the folder and say so.
            button = w.button(
                "Show me how", "",
                lambda: self._explain_self_update())
        button.setFixedWidth(118)
        button.setEnabled(not self._running)
        return button

    # --- acting -------------------------------------------------------------

    def _plan(self) -> None:
        self._log_card.setVisible(True)
        self._log.setPlainText("Reading the update plan…")
        self.jobs.run(self.hermes.update_plan,
                      lambda r: self._log.setPlainText(
                          (r.stdout or r.stderr or "").strip()
                          or "Hermes returned nothing."),
                      lambda e: self._log.setPlainText(e))

    def _update_agent(self) -> None:
        if self._running:
            return
        self._running = True
        self._log_card.setVisible(True)
        self._log.setPlainText("")
        self._message.setText(
            "Updating Hermes. This pulls, reinstalls dependencies and "
            "restarts the gateway, so it takes a while.")
        self.jobs.stream(self.hermes.update_stream, self._on_line,
                         self._on_done, self._on_failed)

    def _update_skills(self) -> None:
        if self._running:
            return
        self._running = True
        self._log_card.setVisible(True)
        self._log.setPlainText("Updating hub skills…")
        self.jobs.run(self.hermes.skills_update_all,
                      lambda r: self._on_done(
                          None, (r.stdout or r.stderr or "").strip()),
                      self._on_failed)

    def _on_line(self, line: str) -> None:
        self._log.setPlainText(self._log.toPlainText() + line + "\n")
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_done(self, _result=None, text: str = "") -> None:
        self._running = False
        if text:
            self._log.setPlainText(text)
        self._message.setText("Finished. Re-checking…")
        self.refresh()

    def _on_failed(self, error: str) -> None:
        self._running = False
        self._message.setText(f"Failed: {error}")
        self.refresh()

    def _explain_self_update(self) -> None:
        root = platforms.app_root()
        self._log_card.setVisible(True)
        self._log.setPlainText(
            f"This app is a git checkout, and pulling it while it is "
            f"running would swap its own code out from under it. Quit it "
            f"first, then:\n\n"
            f"    cd {root}\n"
            f"    git pull\n"
            f"    ./run.sh\n\n"
            f"run.sh reinstalls anything new in the virtualenv on the way "
            f"up, so there is no separate dependency step.")
        try:
            platforms.reveal(root)
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
