"""
Gateway — the long-running process that serves messaging platforms.

One process holds every channel: Telegram, Discord, Slack, WhatsApp, Signal
and the rest, plus the cron scheduler. Connecting a platform needs its token,
which belongs in .env, and most platforms also need a pairing step that only
their own setup flow can do — so this page controls the process and tells the
truth about what it cannot do from here.
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

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

        channels = w.Card("Channels")
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

    def refresh(self) -> None:
        self.jobs.run(self._gather, self._show,
                      lambda e: self._message.setText(e))

    def _gather(self) -> dict:
        return {"status": self.hermes.status(),
                "secrets": set(self.hermes.read_env().keys())}

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
        self._message.setText(
            f"Platforms active: {status.platforms or 'none configured'}")

    def _act(self, action: str) -> None:
        self._message.setText(f"gateway {action}…")
        self.jobs.run(lambda: self.hermes.gateway(action),
                      lambda r: (self._message.setText(
                          "Done." if r.ok else r.message), self.refresh()),
                      lambda e: self._message.setText(e))
