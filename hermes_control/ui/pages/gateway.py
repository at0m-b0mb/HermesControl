"""
Gateway — the long-running process that serves messaging platforms.

One process holds every channel: Telegram, Discord, Slack, WhatsApp, Signal
and the rest, plus the cron scheduler. Connecting a platform needs its token,
which belongs in .env, and most platforms also need a pairing step that only
their own setup flow can do — so this page controls the process and tells the
truth about what it cannot do from here.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QLineEdit, QSpinBox,
                               QVBoxLayout, QWidget)

from ... import email as mail
from .. import widgets as w
from ..shell import Page

#: Platform, the secret that enables it, and how it is set up.
PLATFORMS = [
    ("Telegram", "TELEGRAM_BOT_TOKEN", "Create a bot with @BotFather, paste the token."),
    ("Discord", "DISCORD_BOT_TOKEN", "Create an application, enable the message intent."),
    ("Slack", "SLACK_BOT_TOKEN", "hermes slack manifest generates the app manifest."),
    ("WhatsApp", "", "Pairing only: run hermes whatsapp in a terminal."),
    ("Signal", "", "Pairing only, through signal-cli."),
]


class GatewayPage(Page):
    title = "Gateway"
    group = "Automation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        layout.addWidget(w.PageHeader(
            "Automation", "Gateway",
            "One process, every channel. It also runs the cron schedule."))

        self._control = w.Card("Process", accent=True)
        self._dot = w.StatusDot("idle", "checking")
        self._control.add(self._dot)
        self._start = w.button("Start", "Primary", lambda: self._act("start"))
        self._stop = w.button("Stop", "", lambda: self._act("stop"))
        self._restart = w.button("Restart", "", lambda: self._act("restart"))
        self._control.add(w.row(
            self._start, self._stop, self._restart,
            w.button("Install as a service", "Quiet", lambda: self._act("install")),
            w.spacer()))
        self._control.add(w.label(
            "Installed as a service it starts with your machine. Without that "
            "it only runs while started here.", "Faint", wrap=True))
        layout.addWidget(self._control)

        # --- email ----------------------------------------------------------
        # Email has its own plugin and six settings, so it gets a form rather
        # than a line in a table like the token-only platforms.
        self._email = w.Card("Email")
        self._email.add(w.label(
            "Hermes can poll a mailbox and reply, so anyone allowed can simply "
            "write to the agent. Settings are stored in .env, never in "
            "config.yaml, because they are UPPER_SNAKE keys.", "Faint", wrap=True))

        self._provider = QComboBox()
        self._provider.addItems([p.label for p in mail.PROVIDERS])
        self._provider.currentTextChanged.connect(self._provider_chosen)
        self._address = QLineEdit()
        self._address.setPlaceholderText("you@example.com")
        self._address.editingFinished.connect(self._address_entered)
        self._email.add(w.row(
            self._labelled("PROVIDER", self._provider, 230),
            self._labelled("ADDRESS", self._address, 320), w.spacer()))

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("app password")
        self._imap_host = QLineEdit()
        self._imap_port = QSpinBox()
        self._imap_port.setRange(1, 65535)
        self._imap_port.setValue(993)
        self._smtp_host = QLineEdit()
        self._smtp_port = QSpinBox()
        self._smtp_port.setRange(1, 65535)
        self._smtp_port.setValue(587)
        self._email.add(w.row(
            self._labelled("PASSWORD", self._password, 260),
            self._labelled("ALLOWED SENDERS", self._allowed_field(), 330),
            w.spacer()))
        self._email.add(w.row(
            self._labelled("IMAP HOST", self._imap_host, 230),
            self._labelled("PORT", self._imap_port, 90),
            self._labelled("SMTP HOST", self._smtp_host, 230),
            self._labelled("PORT", self._smtp_port, 90), w.spacer()))

        # currentTextChanged does not fire for the selection a combo box is
        # born with, so the first provider's hosts and its app-password
        # warning would stay blank until the user picked something else.
        self._email_note = w.label("", "Faint", wrap=True)
        self._email.add(self._email_note)
        self._email_status = w.label("", "Faint", wrap=True)
        self._email.add(self._email_status)
        self._email.add(w.row(
            w.button("Save", "Primary", self._save_email),
            w.button("Test connection", "", self._test_email),
            w.spacer()))
        self._provider_chosen(self._provider.currentText())
        layout.addWidget(self._email)

        channels = w.Card("Other channels")
        self._channel_box = QVBoxLayout()
        self._channel_box.setSpacing(4)
        channels.add_layout(self._channel_box)
        channels.add(w.label(
            "Tokens are set on the Models page's pattern — any UPPER_SNAKE key "
            "written through Hermes lands in .env, never in config.yaml. "
            "Per-platform behaviour lives under the gateway section of Config.",
            "Faint", wrap=True))
        layout.addWidget(channels)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    # --- small helpers ------------------------------------------------------

    @staticmethod
    def _labelled(caption: str, widget: QWidget, width: int) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(w.label(caption, "Label"))
        column.addWidget(widget)
        holder.setFixedWidth(width)
        return holder

    def _allowed_field(self) -> QLineEdit:
        self._allowed = QLineEdit()
        self._allowed.setPlaceholderText("you@example.com, colleague@example.com")
        return self._allowed

    def _provider_chosen(self, label: str) -> None:
        provider = mail.provider_for(label)
        if provider is None or provider.label == "Custom":
            self._email_note.setText("")
            return
        self._imap_host.setText(provider.imap_host)
        self._imap_port.setValue(provider.imap_port)
        self._smtp_host.setText(provider.smtp_host)
        self._smtp_port.setValue(provider.smtp_port)
        self._email_note.setText(provider.note)

    def _address_entered(self) -> None:
        """Fill the hosts from the address, so nobody looks them up."""
        guess = mail.guess_provider(self._address.text())
        if guess is not None and not self._imap_host.text():
            self._provider.setCurrentText(guess.label)

    # --- email actions --------------------------------------------------------

    def _email_values(self) -> dict:
        return {
            "EMAIL_ADDRESS": self._address.text().strip(),
            "EMAIL_PASSWORD": self._password.text(),
            "EMAIL_IMAP_HOST": self._imap_host.text().strip(),
            "EMAIL_IMAP_PORT": self._imap_port.value(),
            "EMAIL_SMTP_HOST": self._smtp_host.text().strip(),
            "EMAIL_SMTP_PORT": self._smtp_port.value(),
            "EMAIL_ALLOWED_USERS": self._allowed.text().strip(),
        }

    def _save_email(self) -> None:
        values = self._email_values()
        if not values["EMAIL_ADDRESS"] or not values["EMAIL_SMTP_HOST"]:
            self._email_status.setText(
                "An address and an SMTP host are the minimum.")
            return
        self._email_status.setText("Saving to .env…")

        def work():
            results = []
            for key, value in values.items():
                if value in ("", None):
                    continue
                results.append((key, self.hermes.set_secret(key, str(value))))
            return results

        def done(results):
            bad = [f"{k}: {r.message}" for k, r in results if not r.ok]
            # Never echo a value back, only the key names.
            self._email_status.setText(
                "; ".join(bad) if bad else
                f"Saved {len(results)} setting(s) to .env. "
                f"Restart the gateway for them to take effect.")
            self.refresh()

        self.jobs.run(work, done, lambda e: self._email_status.setText(e))

    def _test_email(self) -> None:
        values = self._email_values()
        password = values["EMAIL_PASSWORD"] or self.hermes.read_env().get(
            "EMAIL_PASSWORD", "")
        address = values["EMAIL_ADDRESS"] or self.hermes.read_env().get(
            "EMAIL_ADDRESS", "")
        if not password:
            self._email_status.setText(
                "Enter the password first — it is only used for this test and "
                "is never shown or logged.")
            return
        self._email_status.setText("Testing…")

        def work():
            return mail.check(address, password,
                              values["EMAIL_IMAP_HOST"], values["EMAIL_IMAP_PORT"],
                              values["EMAIL_SMTP_HOST"], values["EMAIL_SMTP_PORT"])

        def done(result):
            lines = [f"{'ok' if s.ok else 'FAILED'} — {s.name}"
                     + (f": {s.detail}" if s.detail else "")
                     for s in result.stages]
            self._email_status.setText(
                ("Mailbox reachable and sign-in accepted.\n" if result.ok
                 else "") + "\n".join(lines))

        self.jobs.run(work, done, lambda e: self._email_status.setText(e))

    def refresh(self) -> None:
        self.jobs.run(self._gather, self._show,
                      lambda e: self._message.setText(e))

    def _gather(self) -> dict:
        env = self.hermes.read_env()
        return {"status": self.hermes.status(),
                "secrets": set(env.keys()),
                "secrets_full": env}

    def _show(self, data: dict) -> None:
        status = data["status"]
        running = status.gateway_running
        self._dot.set_state("running" if running else "stopped",
                            "running" if running else "stopped")
        self._dot.apply_mode(self.app.mode)
        self._start.setEnabled(not running)
        self._stop.setEnabled(running)
        self._restart.setEnabled(running)
        while self._channel_box.count():
            item = self._channel_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for name, secret, how in PLATFORMS:
            label = w.label(name, "body_bold")
            label.setFixedWidth(110)
            have = bool(secret) and secret in data["secrets"]
            badge = w.Badge("CONFIGURED" if have else "NOT SET",
                            "live" if have else "idle")
            badge.apply_mode(self.app.mode)
            self._channel_box.addWidget(w.row(
                label, badge, w.label(how, "Faint", wrap=True), stretch_last=True))
        env = data["secrets_full"]
        if env.get("EMAIL_ADDRESS") and not self._address.text():
            self._address.setText(env["EMAIL_ADDRESS"])
            self._imap_host.setText(env.get("EMAIL_IMAP_HOST", ""))
            self._smtp_host.setText(env.get("EMAIL_SMTP_HOST", ""))
            self._allowed.setText(env.get("EMAIL_ALLOWED_USERS", ""))
            for key, box in (("EMAIL_IMAP_PORT", self._imap_port),
                             ("EMAIL_SMTP_PORT", self._smtp_port)):
                try:
                    box.setValue(int(env[key]))
                except (KeyError, ValueError):
                    pass
        configured = all(k in env for k in mail.REQUIRED)
        self._email_status.setText(
            "Configured. Restart the gateway after any change."
            if configured else
            "Not configured yet. The password is stored in .env by Hermes and "
            "is never displayed here.")
        self._message.setText(
            f"Platforms active: {status.platforms or 'none configured'}")

    def _act(self, action: str) -> None:
        self._message.setText(f"gateway {action}…")
        self.jobs.run(lambda: self.hermes.gateway(action),
                      lambda r: (self._message.setText(
                          "Done." if r.ok else r.message), self.refresh()),
                      lambda e: self._message.setText(e))
