"""
Runtime — what is installed, where, and whether it is running.

This is the landing page, and it leads with isolation on purpose. Hermes keeps
its whole world in one directory chosen by ``HERMES_HOME``, and its installer
defaults that to a path that may already belong to something else. Hermes
Control always installs to a sibling, and this page says so in as many words,
because "where did my data go" is the worst question a tool can leave you
asking.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ... import platforms
from .. import widgets as w
from ..shell import Page


class RuntimePage(Page):
    title = "Runtime"
    group = "Runtime"
    eyebrow = "Runtime"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(20)

        layout.addWidget(w.PageHeader(
            "Runtime", "Runtime",
            "The Hermes Agent install this app manages, and the services it runs."))

        # --- build ---------------------------------------------------------
        build = w.Card("Build")
        self._build_kv = w.KeyValue()
        build.add(self._build_kv)
        self._build_actions = w.row(
            w.button("Check for updates", "", self._check_update),
            w.button("Run doctor", "", self._run_doctor),
            w.button("Reveal folder", "Quiet", self._reveal),
            w.button("Copy shell command", "Quiet", self._copy_hint),
        )
        build.add(self._build_actions)
        layout.addWidget(build)

        # --- isolation -----------------------------------------------------
        self._isolation = w.Card("Isolation", accent=True)
        self._isolation_kv = w.KeyValue()
        self._isolation.add(self._isolation_kv)
        self._isolation_note = w.label("", "Faint", wrap=True)
        self._isolation.add(self._isolation_note)
        layout.addWidget(self._isolation)

        # --- services ------------------------------------------------------
        services = w.Card("Services")
        self._gateway_dot = w.StatusDot("idle", "checking")
        services.add(w.row(
            w.label("Messaging gateway", "body_bold"),
            self._gateway_dot, stretch_last=True))
        services.add(w.label(
            "The gateway is one process serving every messaging platform you "
            "connect, and it runs the cron schedule. Chat from this app does "
            "not need it.", "Faint", wrap=True))
        # Held as attributes so the live state can switch them: offering
        # "Start" on a gateway that is already up invites a confusing no-op.
        self._gw_start = w.button("Start", "Primary", lambda: self._gateway("start"))
        self._gw_stop = w.button("Stop", "", lambda: self._gateway("stop"))
        self._gw_restart = w.button("Restart", "", lambda: self._gateway("restart"))
        services.add(w.row(self._gw_start, self._gw_stop, self._gw_restart,
                           w.spacer()))
        layout.addWidget(services)

        # --- host ----------------------------------------------------------
        host = w.Card("Host")
        self._host_box = QVBoxLayout()
        self._host_box.setSpacing(6)
        host.add_layout(self._host_box)
        layout.addWidget(host)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    # --- data ---------------------------------------------------------------

    def refresh(self) -> None:
        self._message.setText("Reading installation…")
        self.jobs.run(self._gather, self._show, self._fail)

    def _gather(self) -> dict:
        hermes = self.hermes
        return {
            "installed": hermes.installed,
            "version": hermes.version() if hermes.installed else None,
            "status": hermes.status() if hermes.installed else None,
            "prereqs": platforms.check_prerequisites(),
            "free": platforms.disk_free_gb(hermes.home),
            "config_keys": len(hermes.read_config()),
            "skills": len(hermes.skills()),
            "sessions": len(hermes.sessions(limit=500)),
        }

    def _show(self, data: dict) -> None:
        hermes = self.hermes
        install = hermes.install

        self._build_kv.clear()
        if data["installed"] and data["version"]:
            version = data["version"]
            self._build_kv.add("Version", f"Hermes Agent v{version.version}")
            self._build_kv.add("Channel", version.channel or "unknown")
            self._build_kv.add("Commit", version.commit or "unknown", mono=True)
            self._build_kv.add("Interpreter", version.python or "unknown", mono=True)
            self._build_kv.add("Executable", str(install.executable), mono=True)
        else:
            self._build_kv.add("Version", "Hermes Agent is not installed yet")
            self._build_kv.add("Expected at", str(install.executable), mono=True)

        self._isolation_kv.clear()
        self._isolation_kv.add("Managed home", str(install.hermes_home), mono=True)
        upstream = platforms.default_hermes_home()
        self._isolation_kv.add("Upstream default", str(upstream), mono=True)
        self._isolation_kv.add("Config", str(hermes.config_path), mono=True)
        self._isolation_kv.add("Secrets", str(hermes.env_path), mono=True)
        if upstream.exists() and upstream != install.hermes_home:
            self._isolation_note.setText(
                f"The upstream default {upstream} exists and belongs to something "
                "else. Hermes Control never reads or writes it: every command it "
                "runs carries HERMES_HOME pointing at the managed home above.")
        else:
            self._isolation_note.setText(
                "Every Hermes command this app runs carries HERMES_HOME pointing "
                "at the managed home above, so a second Hermes on this machine "
                "cannot be disturbed.")

        status = data["status"]
        known = status is not None
        running = bool(status and status.gateway_running)
        if known:
            self._gateway_dot.set_state(
                "running" if running else "stopped",
                "running" if running else "stopped")
        else:
            self._gateway_dot.set_state("absent", "unavailable")
        self._gw_start.setEnabled(known and not running)
        self._gw_stop.setEnabled(known and running)
        self._gw_restart.setEnabled(known and running)
        # The primary weight belongs on whichever action is actually available.
        self._gw_start.setObjectName("Primary" if not running else "")
        self._gw_restart.setObjectName("Primary" if running else "")
        for b in (self._gw_start, self._gw_restart):
            b.style().unpolish(b)
            b.style().polish(b)

        while self._host_box.count():
            item = self._host_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for prereq in data["prereqs"]:
            dot = w.StatusDot(
                "ok" if prereq.ok else ("missing" if prereq.required else "warn"),
                prereq.detail)
            dot.apply_mode(self.app.mode)
            name = w.label(prereq.name, "body_bold")
            name.setFixedWidth(90)
            self._host_box.addWidget(w.row(name, dot, stretch_last=True))
        self._host_box.addWidget(w.label(
            f"{data['free']:.0f} GB free on the volume holding the managed home.",
            "Faint"))

        self._message.setText(
            f"{data['config_keys']} settings in config.yaml · "
            f"{data['skills']} skills installed · "
            f"{data['sessions']} sessions recorded")
        self.apply_mode(self.app.mode)

    def _fail(self, error: str) -> None:
        self._message.setText(f"Could not read the installation: {error}")

    # --- actions ------------------------------------------------------------

    def _gateway(self, action: str) -> None:
        self._message.setText(f"Gateway: {action}…")
        self.jobs.run(lambda: self.hermes.gateway(action),
                      lambda r: self._after(r, f"gateway {action}"), self._fail)

    def _check_update(self) -> None:
        self._message.setText("Checking for updates…")
        self.jobs.run(lambda: self.hermes.run(["update", "--check"], timeout=240),
                      lambda r: self._after(r, "update check"), self._fail)

    def _run_doctor(self) -> None:
        self._message.setText("Running doctor…")
        self.jobs.run(lambda: self.hermes.doctor(),
                      lambda r: self._after(r, "doctor"), self._fail)

    def _after(self, result, what: str) -> None:
        head = (result.stdout or result.stderr or "").strip().splitlines()
        summary = next((line.strip() for line in head if line.strip()), "")
        self._message.setText(
            f"{what}: {'ok' if result.ok else result.message}"
            + (f" — {summary[:160]}" if summary else ""))
        self.refresh()

    def _reveal(self) -> None:
        platforms.reveal(self.hermes.home)

    def _copy_hint(self) -> None:
        text = platforms.terminal_hint(self.hermes.install)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._message.setText("Copied: " + text)
