"""Doctor — diagnostics and logs, for when something is wrong."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QVBoxLayout, QWidget

from .. import widgets as w
from ..shell import Page


class DoctorPage(Page):
    title = "Doctor"
    group = "Installation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        layout = QVBoxLayout(self)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(14)

        header = w.PageHeader(
            "Installation", "Doctor",
            "Hermes's own checks, and its logs. Run this first when a turn "
            "fails for no obvious reason.")
        layout.addWidget(header)

        actions = w.row(
            w.button("Run doctor", "Primary", lambda: self._run(["doctor"])),
            w.button("Doctor and fix", "", lambda: self._run(["doctor", "--fix"])),
            w.button("Check config", "", lambda: self._run(["config", "check"])),
            w.button("Full status", "", lambda: self._run(["status", "--full"])),
            w.spacer())
        layout.addWidget(actions)

        picker = w.row(w.label("LOG", "Label"))
        self._log = QComboBox()
        self._log.setFixedWidth(200)
        self._log.currentTextChanged.connect(lambda _: self._load_log())
        picker.layout().addWidget(self._log)
        picker.layout().addWidget(w.button("Reload", "Quiet", self._load_log))
        picker.layout().addStretch(1)
        layout.addWidget(picker)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("MonoEdit")
        layout.addWidget(self._output, 1)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)

    def refresh(self) -> None:
        names = self.hermes.log_names()
        current = self._log.currentText()
        self._log.blockSignals(True)
        self._log.clear()
        self._log.addItems(names or ["(no logs)"])
        if current in names:
            self._log.setCurrentText(current)
        self._log.blockSignals(False)
        if not self._output.toPlainText():
            self._load_log()

    def _load_log(self) -> None:
        name = self._log.currentText()
        if not name or name.startswith("("):
            return
        self.jobs.run(lambda: self.hermes.log_text(name, 400),
                      self._output.setPlainText,
                      lambda e: self._message.setText(e))

    def _run(self, args: list[str]) -> None:
        self._message.setText(f"Running: hermes {' '.join(args)}…")
        self._output.setPlainText("")
        self.jobs.run(lambda: self.hermes.run(args, timeout=420), self._done,
                      lambda e: self._message.setText(e))

    def _done(self, result) -> None:
        self._output.setPlainText(
            (result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
        self._message.setText(
            f"Finished in {result.duration:.1f}s · "
            f"{'no problems reported' if result.ok else result.message}")
