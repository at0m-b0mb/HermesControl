"""
Gateway — the long-running process that serves messaging platforms.

One process holds every channel: Telegram, Discord, Slack, WhatsApp, Signal
and the rest, plus the cron scheduler. Connecting a platform needs its token,
which belongs in .env, and most platforms also need a pairing step that only
their own setup flow can do — so this page controls the process and tells the
truth about what it cannot do from here.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit,
                               QSpinBox, QVBoxLayout, QWidget)

from ... import channels as chan
from ... import email as mail
from ... import platforms
from .. import widgets as w
from ..shell import Page



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
        self._authserv = QLineEdit()
        self._authserv.setPlaceholderText("mx.google.com")
        self._email.add(w.row(
            self._labelled("IMAP HOST", self._imap_host, 230),
            self._labelled("PORT", self._imap_port, 90),
            self._labelled("SMTP HOST", self._smtp_host, 230),
            self._labelled("PORT", self._smtp_port, 90), w.spacer()))
        self._email.add(w.row(
            self._labelled("RECEIVING SERVER ID", self._authserv, 260),
            w.label(mail.AUTHSERV_HELP, "Faint", wrap=True), stretch_last=True))

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

        card = w.Card("Messaging channels")
        card.add(w.label(
            "Whether a channel works is not what is written in .env — it is "
            "whether the gateway can actually reach it. Each row below is "
            "judged by asking the gateway for its delivery targets, which is "
            "the only answer that uses the credentials it really loaded.",
            "Faint", wrap=True))
        self._channel_box = QVBoxLayout()
        self._channel_box.setSpacing(4)
        card.add_layout(self._channel_box)
        self._allow_warning = w.label("", "Faint", wrap=True)
        card.add(self._allow_warning)
        layout.addWidget(card)

        # Proof, rather than inference: a message that arrives came through
        # the gateway's own delivery path, with no model and no agent loop
        # in the way to be blamed for a failure.
        self._proof = w.Card("Prove a channel works")
        self._proof.add(w.label(
            "A channel can be connected and still drop every message, "
            "because the gateway denies anyone not on that channel's "
            "allowlist and says nothing when it does. Sending one message "
            "settles it.", "Faint", wrap=True))
        self._target = QComboBox()
        self._target.setMinimumWidth(240)
        self._test_text = QLineEdit()
        self._test_text.setPlaceholderText("Hermes Control test message")
        self._proof.add(w.row(
            self._labelled("TARGET", self._target, 260),
            self._labelled("MESSAGE", self._test_text, 380), w.spacer()))
        self._send_button = w.button("Send test message", "Primary",
                                     self._send_test)
        self._proof.add(w.row(self._send_button, w.spacer()))
        self._proof_status = w.label("", "Faint", wrap=True)
        self._proof.add(self._proof_status)
        layout.addWidget(self._proof)

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
        self._authserv.setText(provider.authserv_id)
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
            "EMAIL_AUTHSERV_ID": self._authserv.text().strip(),
        }

    def _save_email(self) -> None:
        values = self._email_values()
        if not values["EMAIL_ADDRESS"] or not values["EMAIL_SMTP_HOST"]:
            self._email_status.setText(
                "An address and an SMTP host are the minimum.")
            return
        if not values["EMAIL_AUTHSERV_ID"]:
            # Saving without it produces a mailbox that connects perfectly and
            # answers nobody, with the reason only in a log.
            self._email_status.setText(
                "Receiving server ID is empty. Hermes will refuse to trust "
                "the Authentication-Results header and drop every incoming "
                "message. " + mail.AUTHSERV_HELP)
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
        listed, listing = self.hermes.channel_targets()
        return {"status": self.hermes.status(),
                "survey": chan.survey(env, listing, listed,
                                      "" if listed else listing),
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
        survey = data["survey"]
        words = {"live": ("CONNECTED", "live"),
                 "blocked": ("NOBODY ALLOWED", "attention"),
                 "broken": ("NOT REACHABLE", "fault"),
                 "unknown": ("UNKNOWN", "idle"),
                 "off": ("NOT SET UP", "idle")}
        for state in survey.states:
            label = w.label(state.channel.name, "body_bold")
            label.setFixedWidth(146)
            word, token = words[state.state]
            badge = w.Badge(word, token)
            # Fixed, not minimum: a QLabel will happily absorb the slack in
            # the row, and a pill stretched across half the card stops
            # reading as a status mark at all.
            badge.setFixedWidth(136)
            badge.apply_mode(self.app.mode)
            text = w.label(f"{state.headline} {state.detail}", "Faint",
                           wrap=True)
            text.setMinimumWidth(1)
            # Only offer a step that exists. A "Set up" button on a channel
            # this Hermes has no setup command for would send the user
            # somewhere there is nothing to do.
            action = None
            if state.channel.setup and state.state != "live":
                action = w.button(
                    "Set up", "",
                    lambda c=state.channel: self._setup_channel(c))
                action.setFixedWidth(96)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            line.addWidget(label)
            line.addWidget(badge)
            line.addWidget(text, 1)
            if action is not None:
                line.addWidget(action)
            else:
                line.addSpacing(104)
            self._channel_box.addWidget(holder)

        if not survey.listed:
            self._allow_warning.setText(
                f"The gateway could not be asked which channels it can "
                f"reach, so these rows are read from .env alone and may be "
                f"wrong: {survey.error}")
        elif survey.allow_all:
            self._allow_warning.setText(
                f"{chan.ALLOW_ALL_KEY} is on, so every channel accepts "
                f"messages from anyone who can find it. Each channel's own "
                f"allowlist is being ignored.")
        else:
            self._allow_warning.setText("")

        # The test target list is built from what the gateway says it can
        # reach, so it can never offer a channel that would fail anyway.
        self._target.clear()
        for state in survey.live:
            for target in state.targets or [state.channel.key]:
                self._target.addItem(
                    f"{state.channel.name} — {target}"
                    if target != state.channel.key else state.channel.name,
                    target if ":" in target else state.channel.key)
        has_target = self._target.count() > 0
        self._target.setEnabled(has_target)
        self._send_button.setEnabled(has_target)
        if not has_target:
            self._proof_status.setText(
                "Nothing to test yet — no channel is connected. Email is "
                "separate and is tested with its own button above.")
        env = data["secrets_full"]
        if env.get("EMAIL_ADDRESS") and not self._address.text():
            self._address.setText(env["EMAIL_ADDRESS"])
            self._imap_host.setText(env.get("EMAIL_IMAP_HOST", ""))
            self._smtp_host.setText(env.get("EMAIL_SMTP_HOST", ""))
            self._allowed.setText(env.get("EMAIL_ALLOWED_USERS", ""))
            self._authserv.setText(env.get("EMAIL_AUTHSERV_ID", ""))
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

    def _setup_channel(self, channel) -> None:
        """Hand an interactive setup flow to a real terminal.

        WhatsApp pairing draws a QR code and waits for a phone to scan it.
        Reproducing that inside a widget would mean reimplementing a
        terminal, and a half-drawn QR code is worse than none.
        """
        ok, detail = platforms.open_terminal(
            self.hermes.install, channel.setup.split())
        hint = platforms.terminal_hint(self.hermes.install)
        self._message.setText(
            f"{detail} Finish the pairing there, then press Rescan. "
            f"If nothing opened, run: {hint} {channel.setup}"
            if ok else
            f"{detail} Run this yourself: {hint} {channel.setup}")

    def _send_test(self) -> None:
        target = self._target.currentData()
        if not target:
            return
        text = (self._test_text.text().strip()
                or "Hermes Control test message")
        self._send_button.setEnabled(False)
        self._proof_status.setText(f"Sending to {target}…")

        def done(result) -> None:
            self._send_button.setEnabled(True)
            if result.ok:
                self._proof_status.setText(
                    f"Sent to {target}. If it arrived, that channel works "
                    f"end to end. If it did not, the credentials reach the "
                    f"platform but the destination is wrong.")
            else:
                self._proof_status.setText(
                    f"Not sent: {result.stderr.strip() or result.message}")

        self.jobs.run(lambda: self.hermes.send_test(target, text), done,
                      lambda e: (self._send_button.setEnabled(True),
                                 self._proof_status.setText(e)))

    def _act(self, action: str) -> None:
        self._message.setText(f"gateway {action}…")
        self.jobs.run(lambda: self.hermes.gateway(action),
                      lambda r: (self._message.setText(
                          "Done." if r.ok else r.message), self.refresh()),
                      lambda e: self._message.setText(e))
