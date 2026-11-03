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
        self._sign_in_output = ""

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
        # The flow prints a URL and a short code and then waits. Both have to
        # be on screen and copyable, because the browser does not always open.
        self._portal_code = w.label("", "Mono", wrap=True, select=True)
        self._portal_code.setVisible(False)
        self._portal_card.add(self._portal_code)
        layout.addWidget(self._portal_card)

        self._filter = QLineEdit()
        self._filter.setObjectName("Search")
        self._filter.setPlaceholderText("Filter connectors")
        self._filter.textChanged.connect(lambda _: self._render())
        layout.addWidget(self._filter)

        # Looked for here first and not found, so say where it is rather
        # than leaving the absence to be interpreted as a bug.
        missing = w.Card("Not here", flat=True)
        missing.add(w.label(
            "No email connector exists in this catalogue, and none exists in "
            "the MCP catalogue either. Email is a Hermes gateway platform "
            "rather than a connector: it polls an IMAP mailbox and replies "
            "over SMTP, and it is set up on the Gateway page. Messaging — "
            "Telegram, Discord, Slack, WhatsApp, Signal — is there too. For "
            "tools beyond both catalogues, see MCP.", "Faint", wrap=True))
        missing.add(w.row(
            w.button("Open Gateway", "", lambda: self.app.show_page("Gateway")),
            w.button("Open MCP", "Quiet", lambda: self.app.show_page("MCP")),
            w.spacer()))
        layout.addWidget(missing)

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
            # Signing in and having a subscription are different things, and
            # the Tool Gateway needs the second one. Saying so here stops it
            # looking like the sign-in half worked.
            gateway = []
            if portal.web_tools:
                gateway.append(f"web search {portal.web_tools}")
            if portal.image_tools:
                gateway.append(f"image generation {portal.image_tools}")
            extra = ""
            if gateway and any("not configured" in g for g in gateway):
                extra = ("  The Tool Gateway — web search, image generation — "
                         "is listed as not configured; that needs a Nous "
                         "subscription, separate from the account you just "
                         "signed in with.")
            self._portal_detail.setText(
                "Connectors can be connected. Each one opens a browser "
                "sign-in against that app." + extra)
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
                w.button("No account yet", "", self._open_signup))
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
        self._sign_in_output = ""
        self._portal_code.setVisible(True)
        self._portal_code.setText("Starting sign-in…")
        self._message.setText(
            "A browser should open. If it does not, use the link and code "
            "shown here. Finish it in the browser — this app never handles "
            "those credentials.")
        self._clear(self._portal_actions.layout())
        self._portal_actions.layout().addWidget(
            w.button("Cancel", "Danger", self._cancel_sign_in))
        self._portal_actions.layout().addStretch(1)
        self.jobs.stream(self._connectors.sign_in_stream, self._on_sign_in_line,
                         self._on_sign_in_done, self._failed)

    def _on_sign_in_line(self, line: str) -> None:
        self._sign_in_output += line + "\n"
        url, code = self._connectors.extract_code(self._sign_in_output)
        if url or code:
            parts = []
            if url:
                parts.append(f"Open:  {url}")
            if code:
                parts.append(f"Code:  {code}")
            self._portal_code.setText("\n".join(parts))
        elif line.strip():
            self._portal_code.setText(line.strip()[:200])

    def _on_sign_in_done(self) -> None:
        self._busy = ""
        if self._connectors.signed_in():
            self._portal_code.setVisible(False)
            self._message.setText(
                "Signed in to Nous Portal. Connectors are available now.")
        else:
            self._message.setText(
                "Sign-in did not complete. If you have no Portal account yet, "
                "press 'No account yet' to open the sign-up page.")
        self.refresh()

    def _cancel_sign_in(self) -> None:
        self._connectors.cancel_sign_in()
        self._busy = ""
        self._portal_code.setVisible(False)
        self._message.setText("Sign-in cancelled.")
        self.refresh()

    def _after_sign_in(self, result) -> None:
        """Judge on the state, not the exit code.

        The command this used to run exited 0 without doing anything, and the
        page cheerfully reported success. Asking whether the account is
        actually signed in now is the only answer worth printing.
        """
        self._busy = ""
        if self._connectors.signed_in():
            self._message.setText("Signed in to Nous Portal. Connectors are "
                                  "available now.")
        else:
            detail = result.message if not result.ok else (
                "the sign-in did not complete — if you have no Portal account "
                "yet, press 'No account yet' to open the sign-up page")
            self._message.setText(f"Still not signed in: {detail}")
        self.refresh()

    def _open_signup(self) -> None:
        self._message.setText("Opening the Nous Portal sign-up page…")
        self.jobs.run(self._connectors.open_signup,
                      lambda r: self._message.setText(
                          "Sign-up page opened in your browser."
                          if r.ok else r.message), self._failed)

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
