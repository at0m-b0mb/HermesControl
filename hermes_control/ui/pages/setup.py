"""
Setup — from nothing to a working agent, in order.

The rest of the app assumes Hermes is installed and a model is chosen. This
page is what makes that true, and it is deliberately linear: four steps, each
either satisfied or not, each with exactly one action. "Setup" is Hermes's own
word for this (`hermes setup`), so the page keeps it.

The install runs Nous's own installer and streams its output into the panel
rather than hiding it behind a spinner. A three-gigabyte install that prints
nothing for four minutes looks broken, and the output is also the only way to
see which stage failed when one does.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from ... import platforms, providers
from ...installer import STAGES, Installer, Line
from ...ollama import Ollama, install_hint
from .. import widgets as w
from ..shell import Page


class Step(w.Card):
    """One numbered step: a state, a sentence, and a single action."""

    def __init__(self, number: int, title: str, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.body.addWidget(w.label(f"STEP {number}", "Label"))
        head = w.row(w.label(title, "CardTitle"), w.spacer())
        self.body.addWidget(head)
        self._state = w.StatusDot("idle", "checking")
        self.body.addWidget(self._state)
        self._detail = w.label("", "Faint", wrap=True)
        self.body.addWidget(self._detail)
        self._actions = w.row()
        self.body.addWidget(self._actions)

    def set_state(self, state: str, text: str, detail: str = "") -> None:
        self._state.set_state(state, text)
        self._detail.setText(detail)

    def actions(self):
        return self._actions.layout()

    def clear_actions(self) -> None:
        layout = self._actions.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def apply_mode(self, mode: str) -> None:
        self._state.apply_mode(mode)


class SetupPage(Page):
    title = "Setup"
    group = "Runtime"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._installer_for: Path | None = None
        self.__installer: Installer | None = None
        self._ollama = Ollama()
        self._install_job = None

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        header = w.PageHeader(
            "Runtime", "Setup",
            "Four steps to a working agent. Nothing here writes outside the "
            "managed home shown in step two.")
        header.add_action(w.button("Re-check", "", self.refresh))
        layout.addWidget(header)

        self._s1 = Step(1, "A host that can build it")
        self._s2 = Step(2, "Hermes Agent")
        self._s3 = Step(3, "A model to think with")
        self._s4 = Step(4, "Ready")
        for step in (self._s1, self._s2, self._s3, self._s4):
            layout.addWidget(step)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setObjectName("MonoEdit")
        self._log.setFixedHeight(190)
        self._log.setVisible(False)
        layout.addWidget(self._log)

        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    @property
    def _installer(self) -> Installer:
        """An installer aimed at the home the app is currently driving.

        Binding this once at construction went stale the moment the managed
        home changed — including after this page's own install, which
        re-locates the executable. Rebuilding it when the home moves keeps
        Setup from installing somewhere nothing else reads.
        """
        home = self.hermes.home
        if self.__installer is None or self._installer_for != home:
            self.__installer = Installer(hermes_home=home)
            self._installer_for = home
        return self.__installer

    # --- state --------------------------------------------------------------

    def refresh(self) -> None:
        if self._installer.running:
            return
        self.jobs.run(self._gather, self._show, self._failed)

    def _gather(self) -> dict:
        hermes = self.hermes
        installed = hermes.installed
        model = hermes.config_value("model.default") if installed else None
        provider = hermes.config_value("model.provider") if installed else None
        local_models = []
        if self._ollama.reachable:
            # Probe through providers so the usability test here is the same
            # one the Models page applies: window *and* tool support. Asking
            # only for the window would call a tool-less model ready.
            for server in providers.probe_local():
                if server.name == "Ollama":
                    local_models = server.models
        return {
            "prereqs": platforms.check_prerequisites(),
            "free": platforms.disk_free_gb(self._installer.hermes_home),
            "installed": installed,
            "version": hermes.version().version if installed else "",
            "model": model,
            "provider": provider,
            "ollama": self._ollama.reachable,
            "ollama_version": self._ollama.version() or "",
            "local_models": local_models,
        }

    def _show(self, data: dict) -> None:
        mode = self.app.mode

        # --- step one: the host --------------------------------------------
        missing = [p.name for p in data["prereqs"] if p.required and not p.ok]
        self._s1.clear_actions()
        if missing:
            self._s1.set_state(
                "missing", "not ready",
                "Install these and re-check: " + ", ".join(missing))
        else:
            optional = [p for p in data["prereqs"] if not p.required and not p.ok]
            note = (f"{data['free']:.0f} GB free. Hermes brings its own uv and "
                    f"Node, so nothing else is needed.")
            if optional:
                note += (" Ollama is not installed; it is only needed to run a "
                         "model on this machine.")
            self._s1.set_state("ok", "ready", note)

        # --- step two: Hermes ----------------------------------------------
        self._s2.clear_actions()
        if data["installed"]:
            self._s2.set_state(
                "ok", f"installed, v{data['version']}",
                f"Managed home: {self._installer.hermes_home}")
            self._s2.actions().addWidget(w.button(
                "Reinstall", "Quiet", self._start_install))
            self._s2.actions().addWidget(w.button(
                "Remove", "Danger", self._uninstall))
            self._s2.actions().addStretch(1)
        else:
            problems = self._installer.preflight()
            detail = (f"It will be installed to {self._installer.hermes_home}, "
                      f"never to {platforms.default_hermes_home()}. "
                      f"About 3 GB, several minutes.")
            if problems:
                self._s2.set_state("missing", "cannot install yet",
                                   " ".join(problems))
            else:
                self._s2.set_state("stopped", "not installed", detail)
                button = w.button("Install Hermes Agent", "Primary",
                                  self._start_install)
                self._s2.actions().addWidget(button)
                self._s2.actions().addStretch(1)

        # --- step three: a model -------------------------------------------
        self._s3.clear_actions()
        models = data["local_models"]
        usable = [(m.name, m.context) for m in models
                  if providers.context_verdict(m, 999_999).ok]
        too_small = [(m.name, m.context) for m in models
                     if m.context and m.context < providers.MIN_CONTEXT_WINDOW
                     and m.supports_tools is not False]
        no_tools = [m.name for m in models if m.supports_tools is False]
        if not data["installed"]:
            self._s3.set_state("idle", "waiting on step two", "")
        elif not data["ollama"]:
            self._s3.set_state(
                "warn", "Ollama is not running",
                "For a model on this machine, install and start Ollama: "
                f"{install_hint()}  —  or skip this and use a hosted provider "
                "from the Models page.")
            self._s3.actions().addWidget(w.button(
                "Open Models", "", lambda: self.app.show_page("Models")))
            self._s3.actions().addStretch(1)
        elif not usable:
            detail = (f"Ollama {data['ollama_version']} is running with "
                      f"{len(data['local_models'])} model(s), but none has a "
                      f"context window of {providers.MIN_CONTEXT_WINDOW:,} "
                      f"tokens, which Hermes requires.")
            if too_small:
                detail += ("  Too small: "
                           + ", ".join(f"{n} ({c:,})" for n, c in too_small))
            if no_tools:
                detail += ("  Cannot use tools: " + ", ".join(no_tools)
                           + " — these chat fine but cannot be agents.")
            self._s3.set_state("warn", "no usable model", detail)
            self._s3.actions().addWidget(w.button(
                "Get a model", "Primary", lambda: self.app.show_page("Models")))
            self._s3.actions().addStretch(1)
        else:
            current = str(data["model"] or "")
            chosen = current and any(current == n for n, _ in usable)
            if chosen:
                self._s3.set_state(
                    "ok", f"using {current}",
                    f"{len(usable)} local model(s) clear the floor.")
            else:
                self._s3.set_state(
                    "warn", "a usable model is available but not selected",
                    f"Ready to use: {', '.join(n for n, _ in usable)}")
                best = max(usable, key=lambda item: item[1])
                self._s3.actions().addWidget(w.button(
                    f"Use {best[0]}", "Primary",
                    lambda n=best[0], c=best[1]: self._use(n, c)))
            self._s3.actions().addWidget(w.button(
                "Choose another", "Quiet", lambda: self.app.show_page("Models")))
            self._s3.actions().addStretch(1)

        # --- step four ------------------------------------------------------
        self._s4.clear_actions()
        ready = bool(data["installed"] and data["model"])
        if ready:
            self._s4.set_state(
                "ok", "ready to use",
                f"{data['model']} via {data['provider']}. Open the Console and "
                f"say something.")
            self._s4.actions().addWidget(w.button(
                "Open the Console", "Primary",
                lambda: self.app.show_page("Console")))
            self._s4.actions().addStretch(1)
        else:
            self._s4.set_state("idle", "not yet", "Finish the steps above.")
        self.apply_mode(mode)

    def _failed(self, error: str) -> None:
        self._s1.set_state("error", "could not check", error)

    # --- actions ------------------------------------------------------------

    def _use(self, name: str, window: int) -> None:
        pairs = {
            "model.provider": "ollama",
            "model.base_url": f"{self._ollama.host}/v1",
            "model.default": name,
            "model.api_key": "ollama",
            "model.ollama_num_ctx": min(
                max(window, providers.MIN_CONTEXT_WINDOW), 131_072),
        }

        def work():
            self.hermes.backup_config()
            return [self.hermes.config_set(k, v) for k, v in pairs.items()]

        self.jobs.run(work, lambda _: self.refresh(), self._failed)

    def _start_install(self) -> None:
        self._log.setVisible(True)
        self._log.clear()
        self._progress.setVisible(True)
        self._s2.clear_actions()
        self._s2.actions().addWidget(w.button("Cancel", "Danger", self._cancel))
        self._s2.actions().addStretch(1)
        self._s2.set_state("starting", "installing",
                           "Running Nous's installer. This takes several minutes.")
        self._install_job = self.jobs.stream(
            self._installer.run, self._on_line, self._on_install_done,
            self._failed)

    def _on_line(self, line: Line) -> None:
        self._log.appendPlainText(line.clean)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())
        if line.stage:
            self._s2.set_state("starting", "installing",
                               dict(STAGES).get(line.stage, line.stage))

    def _on_install_done(self) -> None:
        self._progress.setVisible(False)
        self._install_job = None
        # The install changes where the executable is, so re-locate it.
        self.hermes.install = platforms.locate(self._installer.hermes_home)
        self.refresh()
        for key in ("Runtime", "Models", "Console", "Config"):
            page = self.app.page(key)
            if page is not None:
                page.refresh()

    def _cancel(self) -> None:
        self._installer.cancel()
        if self._install_job is not None:
            self._install_job.request_stop()

    def _uninstall(self) -> None:
        def work():
            return self._installer.uninstall()

        def done(result):
            ok, message = result
            self._log.setVisible(True)
            self._log.appendPlainText(message)
            self.hermes.install = platforms.locate(self._installer.hermes_home)
            self.refresh()

        self.jobs.run(work, done, self._failed)

    def apply_mode(self, mode: str) -> None:
        super().apply_mode(mode)
        for step in (self._s1, self._s2, self._s3, self._s4):
            step.apply_mode(mode)
