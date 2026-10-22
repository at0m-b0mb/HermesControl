"""Cron — jobs Hermes runs on a schedule, each in a fresh session."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import widgets as w
from ..shell import Page


class SchedulePage(Page):
    title = "Cron"
    group = "Automation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        header = w.PageHeader(
            "Automation", "Cron",
            "Scheduled work. Each job gets a fresh agent and can deliver its "
            "answer to any platform you have connected.")
        header.add_action(w.button("Reload", "", self.refresh))
        layout.addWidget(header)

        note = w.Card("How jobs run", flat=True)
        note.add(w.label(
            "The scheduler lives in the gateway, so jobs only fire while the "
            "gateway is running. Creating a job is easier in chat — ask Hermes, "
            "or use the /cron command — because it can write the prompt for you.",
            "Faint", wrap=True))
        layout.addWidget(note)

        self._card = w.Card("Jobs")
        self._box = QVBoxLayout()
        self._box.setSpacing(2)
        self._card.add_layout(self._box)
        layout.addWidget(self._card)

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
        return {"jobs": self.hermes.cron_jobs(),
                "gateway": self.hermes.status().gateway_running}

    def _show(self, data: dict) -> None:
        while self._box.count():
            item = self._box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        jobs = data["jobs"]
        if not jobs:
            self._box.addWidget(w.label("No jobs scheduled.", "Faint"))
        for job in jobs:
            if not isinstance(job, dict):
                continue
            name = w.label(str(job.get("name") or job.get("id") or "job"),
                           "body_bold")
            name.setFixedWidth(200)
            when = w.label(str(job.get("schedule") or job.get("cron") or ""),
                           "Mono")
            when.setFixedWidth(150)
            paused = bool(job.get("paused"))
            badge = w.Badge("PAUSED" if paused else "ACTIVE",
                            "idle" if paused else "live")
            badge.apply_mode(self.app.mode)
            job_id = str(job.get("id") or job.get("name") or "")
            run = w.button("Run now", "Quiet",
                           lambda i=job_id: self._act("run", i))
            toggle = w.button("Resume" if paused else "Pause", "Quiet",
                              lambda i=job_id, p=paused:
                              self._act("resume" if p else "pause", i))
            self._box.addWidget(w.row(name, when, badge, w.spacer(), run, toggle))
        self._message.setText(
            f"{len(jobs)} job(s). The gateway is "
            f"{'running, so jobs will fire.' if data['gateway'] else 'stopped, so nothing will fire.'}")

    def _act(self, action: str, job_id: str) -> None:
        if not job_id:
            return
        self._message.setText(f"cron {action} {job_id}…")
        self.jobs.run(
            lambda: self.hermes.run(["cron", action, job_id], timeout=240),
            lambda r: (self._message.setText("Done." if r.ok else r.message),
                       self.refresh()),
            lambda e: self._message.setText(e))
