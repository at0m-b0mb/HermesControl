"""
Console — talk to the agent.

Turns run through ``hermes chat --oneshot --format stream-json``, which is the
one surface Hermes documents as machine-readable. Each line is an event:
``system`` opens the turn and names the session, ``text`` carries output a
fragment at a time, ``tool_use`` and ``tool_result`` narrate what the agent
did, and ``result`` closes with the token accounting.

Those token numbers feed the ribbon at the top, which is the point of this
page as much as the transcript is. Hermes does not truncate a long
conversation — past ``compression.threshold`` of the window it rewrites the
middle into a summary. Knowing you are two turns from that happening changes
what you ask next, so it is shown rather than hidden.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QPlainTextEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from ... import providers, theme
from ...cli import ChatStream, Event
from .. import widgets as w
from ..shell import Page


class ConsolePage(Page):
    title = "Console"
    group = "Runtime"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._stream: ChatStream | None = None
        self._job = None
        self._pending = ""
        self._session = ""
        self._window = 0
        self._tool_depth = 0

        layout = QVBoxLayout(self)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(14)

        header = w.PageHeader(
            "Runtime", "Console",
            "One turn at a time, streamed. Tools run with your permissions.")
        self._model_label = w.label("", "MonoFaint")
        header.add_action(self._model_label)
        layout.addWidget(header)

        self.ribbon = w.ContextRibbon()
        layout.addWidget(self.ribbon)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setObjectName("Mono")
        layout.addWidget(self._transcript, 1)

        options = QHBoxLayout()
        options.setSpacing(10)
        options.addWidget(w.label("TOOLS", "Label"))
        self._toolsets = QComboBox()
        self._toolsets.addItems(["default", "none", "core", "all"])
        self._toolsets.setFixedWidth(120)
        options.addWidget(self._toolsets)
        self._yolo = QCheckBox("skip approval prompts")
        options.addWidget(self._yolo)
        options.addStretch(1)
        self._session_label = w.label("", "Faint")
        options.addWidget(self._session_label)
        layout.addLayout(options)

        self._input = QPlainTextEdit()
        self._input.setObjectName("MonoEdit")
        self._input.setFixedHeight(92)
        self._input.setPlaceholderText(
            "Ask Hermes something.  Ctrl+Enter sends.")
        layout.addWidget(self._input)

        self._send = w.button("Send", "Primary", self.send)
        self._stop = w.button("Stop", "Danger", self.stop)
        self._stop.setEnabled(False)
        self._clear = w.button("New conversation", "Quiet", self.reset)
        self._state = w.label("", "Faint", wrap=True)
        layout.addWidget(w.row(self._state, w.spacer(), self._clear,
                               self._stop, self._send))

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.send)
        QShortcut(QKeySequence("Meta+Return"), self, activated=self.send)

    # --- lifecycle ----------------------------------------------------------

    def refresh(self) -> None:
        self.jobs.run(self._read_setup, self._setup_read, self._setup_failed)

    def _read_setup(self) -> dict:
        hermes = self.hermes
        config = hermes.read_config()
        model_config = config.get("model", {}) if isinstance(config, dict) else {}
        compression = config.get("compression", {}) if isinstance(config, dict) else {}
        window = 0
        for key in ("context_length", "ollama_num_ctx"):
            value = model_config.get(key)
            if isinstance(value, int) and value > window:
                window = value
        return {
            "model": model_config.get("default") or model_config.get("model") or "",
            "provider": model_config.get("provider") or "",
            "window": window,
            "threshold": compression.get("threshold", 0.5),
            "target": compression.get("target_ratio", 0.2),
        }

    def _setup_failed(self, error: str) -> None:
        # Swallowing this silently left the page claiming "no model set" with
        # no way to tell that from a genuinely unset model.
        self._state.setText(f"Could not read the model setup: {error}")

    def _setup_read(self, data: dict) -> None:
        self._window = data["window"]
        self._threshold = float(data["threshold"] or 0.5)
        self._target = float(data["target"] or 0.2)
        where = ("local" if providers.is_local(str(data["provider"])) else "hosted")
        self._model_label.setText(
            f"{data['model'] or 'no model set'}  ·  {where}")
        self.ribbon.set_budget(0, self._window, self._threshold, self._target)
        self.ribbon.apply_mode(self.app.mode)

    # --- transcript ---------------------------------------------------------

    def _append(self, body: str, token: str = "ink", *,
                mono: bool = True, label: str = "") -> None:
        mode = self.app.mode
        colour = theme.color(token, mode)
        faint = theme.color("ink_faint", mode)
        family = theme.mono() if mono else theme.sans()
        head = (f'<div style="color:{faint};font-family:{theme.sans()};'
                f'font-size:10px;letter-spacing:1.2px;margin-top:10px">'
                f'{html.escape(label.upper())}</div>' if label else "")
        text = html.escape(body).replace("\n", "<br>")
        self._transcript.append(
            f'{head}<div style="color:{colour};font-family:{family};'
            f'white-space:pre-wrap">{text}</div>')
        bar = self._transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def reset(self) -> None:
        self.stop()
        self._transcript.clear()
        self._session = ""
        self._session_label.setText("")
        self.ribbon.set_budget(0, self._window, self._threshold, self._target)
        self._state.setText("New conversation.")

    # --- sending ------------------------------------------------------------

    def send(self) -> None:
        prompt = self._input.toPlainText().strip()
        if not prompt or self._stream is not None:
            return
        self._input.clear()
        self._append(prompt, "ink", mono=False, label="you")
        self._pending = ""
        self._tool_depth = 0

        toolsets = self._toolsets.currentText()
        stream = self.hermes.chat(
            prompt,
            toolsets=None if toolsets == "default" else toolsets,
            resume=self._session or None,
            yolo=self._yolo.isChecked(),
        )
        self._stream = stream
        self._send.setEnabled(False)
        self._stop.setEnabled(True)
        self._state.setText("Thinking…")
        self._job = self.jobs.stream(stream.events, self._on_event,
                                     self._on_finished, self._on_failed)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.cancel()
            self._state.setText("Stopped.")
        if self._job is not None:
            self._job.request_stop()

    # --- events -------------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        kind = event.type
        if kind == "system":
            self._session = event.raw.get("session_id") or self._session
            if self._session:
                self._session_label.setText(f"session {self._session[:12]}")
            model = event.raw.get("model")
            if model:
                self._state.setText(f"Running on {model}.")
            return

        if kind == "text":
            self._pending += event.text
            self._state.setText(f"Answering… {len(self._pending)} characters")
            return

        if kind == "tool_use":
            self._flush()
            self._tool_depth += 1
            name = event.tool or "tool"
            self._append(f"calling {name}", "brass", label="tool")
            return

        if kind == "tool_result":
            body = (event.raw.get("content") or event.raw.get("result")
                    or event.text or "")
            body = str(body)
            if len(body) > 700:
                body = body[:700] + f"\n… {len(body) - 700} more characters"
            self._append(body or "(no output)", "ink_muted", label="result")
            return

        if kind == "result":
            self._flush()
            tokens = event.tokens or {}
            total = int(tokens.get("total") or 0)
            if total:
                self.ribbon.set_budget(total, self._window,
                                       self._threshold, self._target)
            if event.error:
                self._append(str(event.error), "fault", mono=False, label="error")
            bits = []
            if total:
                bits.append(f"{total:,} tokens")
            duration = event.raw.get("duration_ms")
            if duration:
                bits.append(f"{int(duration) / 1000:.1f}s")
            if event.exit_code not in (None, 0):
                bits.append(f"exit {event.exit_code}")
            self._state.setText(" · ".join(bits) or "Done.")
            return

    def _flush(self) -> None:
        if self._pending:
            self._append(self._pending, "ink", mono=False, label="hermes")
            self._pending = ""

    def _on_finished(self) -> None:
        self._flush()
        stream = self._stream
        if stream is not None and stream.returncode not in (0, None) \
                and not stream.cancelled:
            detail = stream.stderr.strip().splitlines()
            hint = next((line for line in reversed(detail)
                         if line and not line.startswith("Session:")), "")
            if hint:
                self._append(hint, "fault", label="hermes failed")
        self._stream = None
        self._job = None
        self._send.setEnabled(True)
        self._stop.setEnabled(False)

    def _on_failed(self, error: str) -> None:
        self._append(error, "fault", label="error")
        self._on_finished()

    def apply_mode(self, mode: str) -> None:
        super().apply_mode(mode)
        self.ribbon.apply_mode(mode)
