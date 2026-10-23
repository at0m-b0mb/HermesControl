"""
Connectors — the apps Hermes can act on, and the sign-in they all need.

Every connector is brokered by Nous Portal, so none of them work until the
Portal account is signed in. The connector listing does not say that; each row
simply reads "not connected", which looks like fifty separate problems instead
of one. This page leads with the Portal state for exactly that reason.

Signing in and connecting an account are browser flows against the user's own
accounts, with their own passwords and second factors. The app starts them and
reports the outcome; it does not complete them.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from ...connectors import Connectors
from .. import widgets as w
from ..shell import Page


class ConnectorsPage(Page):
    title = "Connectors"
    group = "Automation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._connectors = Connectors(self.hermes)
        self._busy = ""

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        header = w.PageHeader(
            "Automation", "Connectors",
            "Third-party apps Hermes can act on. Every one of them is brokered "
            "by Nous Portal.")
        header.add_action(w.button("Re-check", "", self.refresh))
        layout.addWidget(header)

        self._portal_card = w.Card("Nous Portal", accent=True)
        self._portal_dot = w.StatusDot("idle", "checking")
        self._portal_card.add(self._portal_dot)
        self._portal_detail = w.label("", "Faint", wrap=True)
        self._portal_card.add(self._portal_detail)
        self._portal_actions = w.row()
        self._portal_card.add(self._portal_actions)
        layout.addWidget(self._portal_card)

        self._filter = QLineEdit()
        self._filter.setObjectName("Search")
        self._filter.setPlaceholderText("Filter connectors")
        self._filter.textChanged.connect(lambda _: self._render())
        layout.addWidget(self._filter)

        self._list_card = w.Card("Apps")
        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(3)
        self._list_card.add_layout(self._list_box)
        layout.addWidget(self._list_card)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))
        self._catalogue = []
        self._portal = None

    # --- data ---------------------------------------------------------------

    def refresh(self) -> None:
        if self._busy:
            return
        self._message.setText("Reading connectors…")
        self._connectors = Connectors(self.hermes)
        self.jobs.run(self._gather, self._show, self._failed)

    def _gather(self) -> dict:
        if not self.hermes.installed:
            return {"installed": False}
        return {
            "installed": True,
            "portal": self._connectors.portal(),
            "catalogue": self._connectors.catalogue(),
            "accounts": self._connectors.accounts(),
        }

    def _show(self, data: dict) -> None:
        if not data.get("installed"):
            self._portal_dot.set_state("absent", "Hermes is not installed")
            self._portal_detail.setText("Install Hermes Agent from Setup first.")
            self._message.setText("")
            self.apply_mode(self.app.mode)
            return

        portal = data["portal"]
        self._portal = portal
        self._catalogue = data["catalogue"]
        self._clear(self._portal_actions.layout())

        if portal.logged_in:
            self._portal_dot.set_state("ok", "signed in")
            self._portal_detail.setText(
                "Connectors can be connected. Each one opens a browser sign-in "
                "against that app.")
        else:
            self._portal_dot.set_state("warn", "not signed in")
            self._portal_detail.setText(
                "This is why every connector below reads 'not connected'. They "
                "are all brokered by Nous Portal, so none of them can work "
                "until this account is signed in — it is one sign-in, not "
                f"{len(self._catalogue)} separate problems.\n\n"
                "Sign-in happens in your browser, with your own password. Press "
                "the button and finish it there; this app does not handle those "
                "credentials.")
            self._portal_actions.layout().addWidget(
                w.button("Sign in to Nous Portal", "Primary", self._portal_login))
        self._portal_actions.layout().addWidget(
            w.button("Copy shell command", "Quiet", self._copy_hint))
        self._portal_actions.layout().addStretch(1)

        accounts = data["accounts"]
        connected = sum(1 for c in self._catalogue if c.connected)
        self._message.setText(
            f"{len(self._catalogue)} connectors · {connected} connected · "
            f"{len(accounts)} account(s)")
        self._render()
        self.apply_mode(self.app.mode)

    def _render(self) -> None:
        self._clear(self._list_box)
        query = self._filter.text().strip().lower()
        shown = [c for c in self._catalogue
                 if not query or query in c.name.lower() or query in c.label.lower()]
        if not shown:
            self._list_box.addWidget(w.label("Nothing matches.", "Faint"))
            return
        signed_in = bool(self._portal and self._portal.logged_in)
        for connector in shown[:80]:
            label = w.label(connector.label, "body_bold")
            label.setFixedWidth(220)
            name = w.label(connector.name, "MonoFaint")
            name.setFixedWidth(230)
            badge = w.Badge("CONNECTED" if connector.connected else "NOT CONNECTED",
                            "live" if connector.connected else "idle")
            badge.apply_mode(self.app.mode)
            if connector.connected:
                action = w.button("Disconnect", "Quiet",
                                  lambda n=connector.name: self._disconnect(n))
            else:
                action = w.button("Connect", "",
                                  lambda n=connector.name: self._connect(n))
                action.setEnabled(signed_in and not self._busy)
                if not signed_in:
                    action.setToolTip("Sign in to Nous Portal first")
            action.setFixedWidth(108)
            self._list_box.addWidget(
                w.row(label, name, badge, w.spacer(), action))
        if len(shown) > 80:
            self._list_box.addWidget(w.label(
                f"{len(shown) - 80} more — use the filter.", "Faint"))

    def _failed(self, error: str) -> None:
        self._busy = ""
        self._message.setText(f"Could not read connectors: {error}")

    # --- actions ------------------------------------------------------------

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _copy_hint(self) -> None:
        from PySide6.QtWidgets import QApplication
        from ... import platforms
        text = (f'HERMES_HOME="{self.hermes.home}" '
                f'"{self.hermes.install.executable}" portal')
        if platforms.IS_WINDOWS:
            text = (f'$env:HERMES_HOME="{self.hermes.home}"; '
                    f'& "{self.hermes.install.executable}" portal')
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._message.setText("Copied: " + text)

    def _portal_login(self) -> None:
        self._busy = "portal"
        self._message.setText(
            "Opening Nous Portal sign-in in your browser. Finish it there, "
            "then press Re-check.")
        self.jobs.run(
            lambda: self.hermes.run(["portal"], timeout=600),
            lambda r: self._after(r, "Portal sign-in"), self._failed)

    def _connect(self, app_name: str) -> None:
        self._busy = app_name
        self._message.setText(
            f"Opening the {app_name} sign-in in your browser. Finish it there — "
            f"this app does not handle those credentials.")
        self._render()
        self.jobs.run(lambda: self._connectors.connect(app_name),
                      lambda r: self._after(r, f"Connect {app_name}"), self._failed)

    def _disconnect(self, app_name: str) -> None:
        self._busy = app_name
        self._message.setText(f"Disconnecting {app_name}…")
        self.jobs.run(lambda: self._connectors.disconnect(app_name),
                      lambda r: self._after(r, f"Disconnect {app_name}"), self._failed)

    def _after(self, result, what: str) -> None:
        self._busy = ""
        self._message.setText(
            f"{what}: {'done' if result.ok else result.message}")
        self.refresh()
