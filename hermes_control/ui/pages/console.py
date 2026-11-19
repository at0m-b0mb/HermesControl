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
import json
import re
from pathlib import Path

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QPlainTextEdit, QTextEdit, QVBoxLayout,
    QWidget,
)

from ... import briefing, providers, theme, toolsets
from ...cli import ChatStream, Event
from .. import widgets as w
from ..shell import Page


def _arguments(raw: object, limit: int = 160) -> str:
    """Render a tool call's arguments compactly.

    ``{'path': 'notes.txt'}`` reads better as ``path=notes.txt``, and a
    long ``content`` is summarised by size rather than dumped — the point
    is to show what the agent is doing, not to reproduce the file it is
    writing.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return raw[:limit]
    if not isinstance(raw, dict):
        return "" if raw is None else str(raw)[:limit]
    bits: list[str] = []
    for key, value in raw.items():
        text = value if isinstance(value, str) else json.dumps(value)
        if len(text) > 60:
            text = f"<{len(text)} chars>"
        bits.append(f"{key}={text}")
    joined = "  ".join(bits)
    return joined if len(joined) <= limit else joined[:limit] + "\u2026"


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
        self._ready = False
        saved = str(app.settings.value("console/workdir", ""))
        self._workdir = (Path(saved) if saved and Path(saved).is_dir()
                         else Path.home())
        self._empty = False

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

        # What is happening right now, on one line. The transcript is the
        # record; this is the pulse, and during a long tool call it is the
        # only thing that distinguishes working from hung.
        self._activity = w.label("", "MonoFaint")
        layout.addWidget(self._activity)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setObjectName("Mono")
        layout.addWidget(self._transcript, 1)

        options = QHBoxLayout()
        options.setSpacing(10)
        options.addWidget(w.label("TOOLS", "Label"))
        self._toolsets = QComboBox()
        # These used to be "default / none / core / all", three of which this
        # app invented: `none` and `core` are rejected by Hermes and failed
        # every turn they were selected for. See hermes_control.toolsets.
        for choice in toolsets.CHOICES:
            self._toolsets.addItem(choice.label)
        self._toolsets.setFixedWidth(190)
        self._toolsets.setToolTip(toolsets.CHOICES[0].detail)
        # Remembered across restarts. Someone who has settled on a narrow
        # toolset -- because their local model drowns in the full one -- should
        # not have to re-pick it every time the app opens.
        remembered = str(self.app.settings.value("console/toolsets", ""))
        if toolsets.choice_for(remembered) is not None:
            self._toolsets.setCurrentText(remembered)
        self._toolsets.currentTextChanged.connect(self._tools_changed)
        options.addWidget(self._toolsets)
        self._yolo = QCheckBox("skip approval prompts")
        options.addWidget(self._yolo)
        options.addSpacing(14)
        # Where the agent's file and shell tools operate. Without this the
        # turn inherits the *gateway's* working directory -- the Hermes
        # checkout -- so "write notes.txt" landed inside the installation.
        options.addWidget(w.label("IN", "Label"))
        self._workdir_label = w.label("", "MonoFaint")
        options.addWidget(self._workdir_label)
        options.addWidget(w.button("Change", "Quiet", self._choose_workdir))
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
        model_name = (model_config.get("default")
                      or model_config.get("model") or "")
        provider_key = model_config.get("provider") or ""

        # The ribbon must draw the window the server will actually serve.
        # `ollama_num_ctx` is a request, and LM Studio ignores it entirely:
        # it serves whatever the model was loaded at. Drawing the configured
        # number would put the compaction mark in the wrong place on a meter
        # whose whole purpose is to show where compaction happens.
        served = 0
        served_by = ""
        if providers.is_local(provider_key):
            for server in providers.probe_local():
                if not server.reachable:
                    continue
                for model in server.models:
                    if model.name == model_name and model.loaded:
                        served = model.effective_context
                        served_by = server.name
        skills = hermes.skills()
        prompt_ok, prompt_text = hermes.prompt_size()
        return {
            "installed": hermes.installed,
            "model": model_name,
            "provider": provider_key,
            "window": served or window,
            "served_by": served_by,
            "threshold": compression.get("threshold", 0.5),
            "target": compression.get("target_ratio", 0.2),
            "briefing": briefing.build(
                prompt_text, prompt_ok, model=model_name,
                provider=served_by or provider_key, window=served or window,
                workdir=str(self._workdir), skills=len(skills),
                skills_broken=sum(1 for s in skills if s.get("missing")),
                error="" if prompt_ok else prompt_text),
        }

    def _setup_failed(self, error: str) -> None:
        # Swallowing this silently left the page claiming "no model set" with
        # no way to tell that from a genuinely unset model.
        self._state.setText(f"Could not read the model setup: {error}")

    def _setup_read(self, data: dict) -> None:
        self._briefing = data.get("briefing")
        self._window = data["window"]
        self._threshold = float(data["threshold"] or 0.5)
        self._target = float(data["target"] or 0.2)
        model = str(data["model"] or "")
        provider = str(data["provider"] or "")
        if not data["installed"]:
            self._model_label.setText("Hermes Agent is not installed")
        elif not model:
            self._model_label.setText("no model set")
        else:
            # "hosted" was being claimed for an unset provider, because
            # is_local("") is False. Only say where it runs once we know.
            where = str(data.get("served_by") or
                        ("local" if providers.is_local(provider) else "hosted"))
            window = data["window"]
            self._model_label.setText(
                f"{model}  ·  {where}" +
                (f"  ·  {int(window):,} tokens" if window else ""))

        # Offering Send when a turn cannot possibly start produces a stack
        # trace instead of an answer. Say why, and point at the fix.
        self._ready = bool(data["installed"] and model)
        self._send.setEnabled(self._ready and self._stream is None)
        self._input.setEnabled(self._ready)
        if not data["installed"]:
            self._state.setText(
                "Hermes Agent is not installed yet — open Setup to install it.")
            self._input.setPlaceholderText("")
        elif not model:
            self._state.setText(
                "No model is selected — choose one on the Models page.")
            self._input.setPlaceholderText("")
        else:
            self._input.setPlaceholderText(
                "Ask Hermes something.  Ctrl+Enter sends.")
            if not self._transcript.toPlainText():
                self._state.setText("")

        self._show_workdir()
        if getattr(self, "_empty", False) or not self._transcript.toPlainText().strip():
            self._show_empty_state()
        self.ribbon.set_budget(0, self._window, self._threshold, self._target)
        self.ribbon.apply_mode(self.app.mode)

    def _choose_workdir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(
            self, "Where should the agent work?", str(self._workdir))
        if chosen:
            self._workdir = Path(chosen)
            self.app.settings.setValue("console/workdir", chosen)
            self._show_workdir()

    def _show_workdir(self) -> None:
        text = str(self._workdir)
        home = str(Path.home())
        if text.startswith(home):
            text = "~" + text[len(home):]
        if len(text) > 34:
            text = "…" + text[-33:]
        self._workdir_label.setText(text)
        self._workdir_label.setToolTip(str(self._workdir))

    def _tools_changed(self, label: str) -> None:
        choice = toolsets.choice_for(label)
        self._toolsets.setToolTip(choice.detail if choice else "")
        if choice is not None:
            self._state.setText(choice.detail)
            self.app.settings.setValue("console/toolsets", label)

    # --- transcript ---------------------------------------------------------

    def _append(self, body: str, token: str = "ink", *,
                mono: bool = True, label: str = "") -> None:
        self._clear_empty_state()
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

    def _show_empty_state(self) -> None:
        """Brief the user on what this agent can actually do.

        A QTextEdit placeholder renders only its first line, so this is
        written as real content and cleared on the first message. On first
        open the panel is most of the window, and the question everyone
        has — *can it really touch my files?* — is answerable here from
        the tool schemas Hermes reports it is sending, rather than left
        to be discovered by trying.
        """
        mode = self.app.mode
        faint = theme.color("ink_faint", mode)
        muted = theme.color("ink_muted", mode)
        brass = theme.color("brass", mode)
        ink = theme.color("ink", mode)
        mono = theme.mono()
        sans = theme.sans()
        brief = getattr(self, "_briefing", None)

        def rule(title: str) -> str:
            return (f'<p style="color:{brass};font-family:{sans};font-size:10px;'
                    f'letter-spacing:1.4px;margin-top:16px;margin-bottom:2px">'
                    f'{html.escape(title)}</p>')

        rows: list[str] = []
        if brief is not None:
            facts = [("MODEL", brief.model or "none selected"),
                     ("SERVED BY", brief.provider or "unknown"),
                     ("WINDOW", f"{brief.window:,} tokens" if brief.window
                      else "unknown"),
                     ("WORKING IN", brief.workdir)]
            if brief.window and brief.read:
                facts.append((
                    "ROOM TO TALK",
                    f"~{brief.headroom():,} tokens after the system prompt "
                    f"and tool schemas"))
            rows.append(
                '<table cellpadding="0" cellspacing="0">' + "".join(
                    f'<tr><td style="color:{faint};font-family:{sans};'
                    f'font-size:10px;letter-spacing:1.2px;padding-right:18px">'
                    f'{k}</td><td style="color:{ink};font-family:{mono};'
                    f'font-size:12px">{html.escape(str(v))}</td></tr>'
                    for k, v in facts) + "</table>")

        if brief is not None and brief.read and brief.toolsets:
            rows.append(rule(f"{brief.tool_count} TOOLS IN {len(brief.toolsets)} SETS"))
            for toolset in brief.toolsets:
                plain = toolset.plain
                rows.append(
                    f'<div style="font-family:{mono};font-size:12px;'
                    f'color:{ink}">{html.escape(toolset.name)}'
                    f'<span style="color:{faint}"> &times;{toolset.tools}</span>'
                    + (f'<span style="color:{muted};font-family:{sans}">'
                       f' &nbsp;&nbsp;{html.escape(plain)}</span>' if plain else "")
                    + "</div>")
            can = []
            if brief.can_edit_files:
                can.append("edit files")
            if brief.can_run_commands:
                can.append("run commands")
            if brief.can_see_images:
                can.append("read images")
            if can:
                rows.append(
                    f'<p style="color:{muted};font-family:{sans};font-size:13px;'
                    f'margin-top:10px">This model is being handed tools to '
                    f'<b style="color:{ink}">{html.escape(", ".join(can))}</b>. '
                    f'Whether it uses them competently is a separate question '
                    f'— ask it to do something in two steps and watch.</p>')
        elif brief is not None and not brief.read:
            rows.append(
                f'<p style="color:{muted};font-family:{sans};font-size:13px">'
                f'The tool list could not be read, so what this agent can do '
                f'is not stated here rather than guessed at. '
                f'{html.escape(brief.error[:200])}</p>')

        if brief is not None and brief.skills:
            broken = (f' &nbsp;<span style="color:{theme.color("fault", mode)}">'
                      f'{brief.skills_broken} cannot run</span>'
                      if brief.skills_broken else "")
            rows.append(rule("SKILLS"))
            rows.append(
                f'<div style="font-family:{mono};font-size:12px;color:{ink}">'
                f'{brief.skills} installed{broken}</div>')

        rows.append(
            f'<p style="color:{muted};font-family:{sans};font-size:13px;'
            f'margin-top:16px">Ask something and the reply streams in as it '
            f'is generated. Every tool call appears here with its arguments '
            f'and how long it took. The meter above shows how full the '
            f'window is and where Hermes starts compacting the conversation '
            f'rather than truncating it.</p>')

        self._transcript.setHtml(
            f'<div style="line-height:150%">'
            f'<p style="color:{brass};font-family:{sans};font-size:10px;'
            f'letter-spacing:1.4px">READY</p>' + "".join(rows) + "</div>")
        self._empty = True

    def _clear_empty_state(self) -> None:
        if getattr(self, "_empty", False):
            self._transcript.clear()
            self._empty = False

    def reset(self) -> None:
        self.stop()
        self._transcript.clear()
        self._show_empty_state()
        self._session = ""
        self._session_label.setText("")
        self.ribbon.set_budget(0, self._window, self._threshold, self._target)
        self._state.setText("New conversation.")

    # --- sending ------------------------------------------------------------

    def send(self) -> None:
        prompt = self._input.toPlainText().strip()
        if not prompt or self._stream is not None or not self._ready:
            return
        self._input.clear()
        self._append(prompt, "ink", mono=False, label="you")
        self._pending = ""
        self._tool_depth = 0

        choice = toolsets.choice_for(self._toolsets.currentText())
        stream = self.hermes.chat(
            prompt,
            toolsets=choice.value if choice else None,
            resume=self._session or None,
            yolo=self._yolo.isChecked(),
            cwd=self._workdir,
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
            # Keep whatever arrived before the stop and say plainly that it is
            # incomplete. Discarding it left two of the user's own messages
            # adjacent in the transcript with nothing to show a turn had ever
            # been started, which reads as a lost message rather than a
            # cancelled one.
            partial = self._pending
            self._pending = ""
            if partial.strip():
                self._append(partial, "ink", mono=False, label="hermes")
            self._append("You stopped this turn; the reply above is "
                         "incomplete." if partial.strip() else
                         "You stopped this turn before it answered.",
                         "attention", mono=False, label="stopped")
            self._state.setText("Stopped.")
        if self._job is not None:
            self._job.request_stop()

    # --- events -------------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        kind = event.type
        if kind == "system":
            # The system event declares a session_id field and leaves it
            # empty; the real id only arrives on the closing result event (and
            # on stderr). Reading it here alone meant --resume was never
            # passed and every turn silently started a new conversation.
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
            # The arguments are the interesting part. "calling read_file"
            # says the agent did something; "read_file path=notes.txt" says
            # what, which is the difference between watching a turn and
            # being able to check it.
            self._append(f"{name}  {_arguments(event.raw.get('input'))}",
                         "brass", label="tool")
            self._activity.setText(f"\u25b8 {name} {_arguments(event.raw.get('input'))}"[:120])
            return

        if kind == "tool_result":
            body = str(event.output)
            if len(body) > 700:
                body = body[:700] + f"\n\u2026 {len(body) - 700} more characters"
            took = event.raw.get("duration_ms")
            failed = bool(event.raw.get("is_error"))
            tag = "result"
            if took:
                tag = f"result · {int(took)} ms"
            if failed:
                tag = f"{tag} · FAILED"
            self._append(body or "(no output)",
                         "fault" if failed else "ink_muted", label=tag)
            self._activity.setText("")
            return

        if kind == "result":
            self._flush()
            self._session = event.raw.get("session_id") or self._session
            if self._session:
                self._session_label.setText(f"session {self._session[:12]}")
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
        if stream is not None and not self._session:
            # A turn that fails before its result event still printed the id
            # on stderr; keeping it means the next message continues the same
            # conversation rather than quietly abandoning it.
            match = re.search(r"Session:\s*(\S+)", stream.stderr)
            if match:
                self._session = match.group(1)
                self._session_label.setText(f"session {self._session[:12]}")
        if stream is not None and stream.returncode not in (0, None) \
                and not stream.cancelled:
            detail = stream.stderr.strip().splitlines()
            hint = next((line for line in reversed(detail)
                         if line and not line.startswith("Session:")), "")
            if hint:
                self._append(hint, "fault", label="hermes failed")
        self._stream = None
        self._job = None
        self._send.setEnabled(self._ready)
        self._stop.setEnabled(False)

    def _on_failed(self, error: str) -> None:
        self._append(error, "fault", label="error")
        self._on_finished()

    def apply_mode(self, mode: str) -> None:
        super().apply_mode(mode)
        self.ribbon.apply_mode(mode)
