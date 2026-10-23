"""
Config — every setting Hermes documents, editable.

The promise of this page is completeness, and it keeps it by not having a
curated list of settings in it. :mod:`hermes_control.confschema` derives the
schema from the annotated ``config.yaml`` that ships with the install, so this
page shows whatever that version of Hermes supports, including options added
after this code was written, with upstream's own prose as the help text.

Editing is deliberately two-stage. Changes accumulate as pending edits and
nothing touches disk until Apply, which takes a backup first and then writes
each key through ``hermes config set`` so Hermes validates it and decides
whether it belongs in ``config.yaml`` or ``.env``. A key that Hermes rejects
is reported against its own row rather than failing the batch silently.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ... import confschema
from .. import widgets as w
from ..shell import Page

_UNSET = object()

#: Enums upstream documents in prose the parser cannot reliably read. Keeping
#: them here rather than widening the parser's guesswork: a wrong dropdown
#: hides valid values, which is worse than a plain text field.
CHOICE_OVERRIDES: dict[str, list[str]] = {
    "terminal.backend": ["local", "docker", "ssh", "modal", "daytona",
                         "vercel_sandbox", "singularity"],
    "terminal.home_mode": ["auto", "real", "profile"],
    "updates.pre_update_backup": ["quick", "full", "off"],
    "updates.non_interactive_local_changes": ["stash", "discard"],
    "database.journal_mode": ["wal", "delete"],
    "database.synchronous": ["OFF", "NORMAL", "FULL", "EXTRA"],
    "compression.tail_mode": ["lean", "legacy"],
    "model.provider": [
        "auto", "openrouter", "nous", "nous-api", "anthropic", "openai-codex",
        "copilot", "gemini", "zai", "kimi-coding", "minimax", "minimax-cn",
        "huggingface", "nvidia", "xiaomi", "arcee", "ollama-cloud", "deepinfra",
        "kilocode", "ai-gateway", "azure-foundry", "lmstudio", "custom",
        "ollama", "vllm", "llamacpp",
    ],
}


class OptionRow(QWidget):
    """One setting: its key, an editor suited to its type, and its help."""

    def __init__(self, option: confschema.Option, mode: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.option = option
        self._original = option.value
        self._editor: QWidget
        self._mode = mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        key = w.label(option.path, "Mono", select=True)
        head.addWidget(key)
        self._badge = w.Badge("NOT SET" if option.commented else "SET",
                              "idle" if option.commented else "live")
        self._badge.apply_mode(mode)
        head.addWidget(self._badge)
        head.addStretch(1)
        self._state = w.label("", "Faint")
        head.addWidget(self._state)
        layout.addLayout(head)

        self._secret = False
        self._editor = self._build_editor(option)
        if self._secret:
            reveal = w.button("Reveal", "Quiet", self._toggle_reveal)
            reveal.setCheckable(True)
            self._reveal = reveal
            layout.addWidget(w.row(self._editor, reveal, stretch_last=False))
        else:
            layout.addWidget(self._editor)

        if option.help:
            text = option.help if len(option.help) < 600 else option.help[:600] + "…"
            help_label = w.label(text, "Faint", wrap=True)
            layout.addWidget(help_label)
        if option.inline and option.inline not in (option.help or ""):
            layout.addWidget(w.label(option.inline, "Faint", wrap=True))
        layout.addWidget(w.rule())

    # --- editors ----------------------------------------------------------

    def _choices(self) -> list[str]:
        return CHOICE_OVERRIDES.get(self.option.path) or self.option.choices

    def _build_editor(self, option: confschema.Option) -> QWidget:
        choices = self._choices()
        current = option.value if option.value is not None else option.default

        if choices:
            box = QComboBox()
            values = list(choices)
            if current is not None and str(current) not in values:
                values.insert(0, str(current))
            box.addItems(values)
            if current is not None:
                box.setCurrentText(str(current))
            box.currentTextChanged.connect(self._touched)
            return box

        if option.kind == "bool" or isinstance(current, bool):
            check = QCheckBox("enabled")
            check.setChecked(bool(current))
            check.stateChanged.connect(self._touched)
            return check

        if option.kind == "int" and not isinstance(current, bool):
            spin = QSpinBox()
            spin.setRange(-2_147_483_648, 2_147_483_647)
            spin.setValue(int(current) if isinstance(current, int) else 0)
            spin.setGroupSeparatorShown(True)
            spin.valueChanged.connect(self._touched)
            return spin

        if option.kind == "float":
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(4)
            spin.setSingleStep(0.05)
            spin.setValue(float(current) if isinstance(current, (int, float)) else 0.0)
            spin.valueChanged.connect(self._touched)
            return spin

        if option.kind in ("list", "map"):
            editor = QPlainTextEdit()
            editor.setObjectName("MonoEdit")
            editor.setFixedHeight(84)
            if current is not None:
                editor.setPlainText(yaml.safe_dump(current, sort_keys=False).strip())
            editor.setPlaceholderText("YAML or JSON")
            editor.textChanged.connect(self._touched)
            return editor

        line = QLineEdit()
        line.setText("" if current is None else str(current))
        line.setPlaceholderText("not set" if option.value is None else "")
        if confschema.is_secret(option.path):
            # Hermes masks credentials in `config get`; reading the file
            # directly must not be the way they end up on a screenshot.
            line.setEchoMode(QLineEdit.EchoMode.Password)
            self._secret = True
        line.textChanged.connect(self._touched)
        return line

    # --- value ------------------------------------------------------------

    def value(self) -> Any:
        """The editor's current value, typed, or ``_UNSET`` when left blank."""
        editor = self._editor
        if isinstance(editor, QComboBox):
            return editor.currentText()
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, QSpinBox):
            return editor.value()
        if isinstance(editor, QDoubleSpinBox):
            return round(editor.value(), 6)
        if isinstance(editor, QPlainTextEdit):
            text = editor.toPlainText().strip()
            if not text:
                return _UNSET
            try:
                return yaml.safe_load(text)
            except yaml.YAMLError:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        if isinstance(editor, QLineEdit):
            text = editor.text().strip()
            if not text:
                return _UNSET
            if text.lower() in ("true", "false"):
                return text.lower() == "true"
            if text.lower() in ("null", "none"):
                return None
            try:
                return int(text)
            except ValueError:
                pass
            try:
                return float(text)
            except ValueError:
                pass
            return text
        return _UNSET

    @property
    def changed(self) -> bool:
        value = self.value()
        if value is _UNSET:
            return self._original is not None
        return value != self._original

    def _touched(self, *_: object) -> None:
        self._state.setText("edited" if self.changed else "")
        parent = self.parent()
        while parent is not None and not isinstance(parent, ConfigPage):
            parent = parent.parent()
        if isinstance(parent, ConfigPage):
            parent.recount()

    def mark_saved(self, value: Any) -> None:
        self._original = value
        self._state.setText("")
        self._badge.setText("SET")
        self._badge.set_token("live")

    def mark_error(self, message: str) -> None:
        self._state.setText(message[:90])

    def _toggle_reveal(self) -> None:
        if not isinstance(self._editor, QLineEdit):
            return
        hidden = self._editor.echoMode() == QLineEdit.EchoMode.Password
        self._editor.setEchoMode(QLineEdit.EchoMode.Normal if hidden
                                 else QLineEdit.EchoMode.Password)
        self._reveal.setText("Hide" if hidden else "Reveal")

    def apply_mode(self, mode: str) -> None:
        self._mode = mode
        self._badge.apply_mode(mode)


class ConfigPage(Page):
    title = "Config"
    group = "Installation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._schema: confschema.Schema | None = None
        self._rows: list[OptionRow] = []
        self._section = ""

        outer = QVBoxLayout(self)
        pad = 32
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(16)

        header = w.PageHeader(
            "Installation", "Config",
            "Every option this Hermes build documents, read from the annotated "
            "config.yaml it shipped with. Help text is upstream's own.")
        self._count = w.label("", "Faint")
        header.add_action(self._count)
        outer.addWidget(header)

        self._search = QLineEdit()
        self._search.setObjectName("Search")
        self._search.setPlaceholderText(
            "Search every option by key, section or description")
        self._search.textChanged.connect(self._on_search)
        outer.addWidget(self._search)

        split = QHBoxLayout()
        split.setSpacing(16)
        self._sections = QListWidget()
        self._sections.setFixedWidth(310)
        self._sections.currentItemChanged.connect(self._on_section)
        split.addWidget(self._sections)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 8, 0)
        self._body_layout.setSpacing(0)
        self._scroll = w.scroller(self._body)
        split.addWidget(self._scroll, 1)
        outer.addLayout(split, 1)

        self._message = w.label("", "Faint", wrap=True)
        self._apply = w.button("Apply changes", "Primary", self._apply_changes)
        self._revert = w.button("Revert", "", self.refresh)
        self._apply.setEnabled(False)
        self._revert.setEnabled(False)
        footer = w.row(self._message, w.spacer(), self._revert, self._apply)
        outer.addWidget(footer)

    # --- loading ----------------------------------------------------------

    def refresh(self) -> None:
        self._message.setText("Reading config.yaml…")
        self.jobs.run(self._load, self._loaded, self._failed)

    def _load(self) -> confschema.Schema | None:
        path = self.hermes.config_path
        if not path.exists():
            return None
        schema = confschema.parse(path)
        # The annotated file carries shipped defaults; the live file carries
        # what is actually set. Overlay the latter so the editor shows truth.
        live = self.hermes.read_config()
        for option in schema.options:
            node: Any = live
            for part in option.path.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    node = _UNSET
                    break
            if node is not _UNSET:
                option.value = node
                option.commented = False
        return schema

    def _loaded(self, schema: confschema.Schema | None) -> None:
        if schema is None:
            self._message.setText(
                "No config.yaml yet — install Hermes from the Runtime page first.")
            return
        self._schema = schema
        grouped = schema.by_section()
        self._sections.blockSignals(True)
        self._sections.clear()
        for section in schema.sections:
            options = self._visible(grouped.get(section, []))
            if not options:
                continue
            item = QListWidgetItem(f"{section}   ({len(options)})")
            item.setData(Qt.ItemDataRole.UserRole, section)
            self._sections.addItem(item)
        self._sections.blockSignals(False)
        active = sum(1 for o in schema.options if not o.commented)
        self._count.setText(
            f"{len(schema.options)} options · {active} set · "
            f"schema v{schema.config_version}")
        # A refresh can land while the user is mid-search — reading the config
        # takes a moment and typing does not wait for it. Re-rendering the
        # selected section here would silently throw their results away, so
        # the search wins when there is one.
        query = self._search.text().strip()
        if self._sections.count():
            target = 0
            for index in range(self._sections.count()):
                if self._sections.item(index).data(
                        Qt.ItemDataRole.UserRole) == self._section:
                    target = index
                    break
            self._sections.blockSignals(bool(query))
            self._sections.setCurrentRow(target)
            self._sections.blockSignals(False)
        if query:
            self._on_search(query)
        elif not self._sections.count():
            self._render([])
        self._message.setText("")

    def _failed(self, error: str) -> None:
        self._message.setText(f"Could not read the config: {error}")

    # --- rendering --------------------------------------------------------

    def _on_section(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None or self._schema is None:
            return
        self._section = current.data(Qt.ItemDataRole.UserRole)
        options = [o for o in self._schema.options if o.section == self._section]
        self._render(options)

    def _on_search(self, text: str) -> None:
        if self._schema is None:
            return
        if not text.strip():
            self._sections.setEnabled(True)
            self._on_section(self._sections.currentItem())
            return
        self._sections.setEnabled(False)
        self._render(self._schema.search(text)[:160], searching=True)

    def _visible(self, options: list[confschema.Option]) -> list[confschema.Option]:
        """Drop container keys whose children are already shown.

        Offering `database` as a YAML blob directly above `database.journal_mode`
        invites two editors to disagree about one value. A map with no children
        in the schema (an open-ended dict like `terminal.docker_env`) is kept,
        because there it is the only way to edit the thing.
        """
        if self._schema is None:
            return options
        parents = {o.path.rsplit(".", 1)[0] for o in self._schema.options
                   if "." in o.path}
        return [o for o in options
                if not (o.kind == "map" and o.path in parents)]

    def _render(self, options: list[confschema.Option], searching: bool = False) -> None:
        # A container's own prose explains the whole group, so hiding the
        # container must not take its explanation with it.
        preamble = [o for o in options
                    if o not in self._visible(options) and o.help]
        options = self._visible(options)
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []

        if not options:
            self._body_layout.addWidget(w.label("Nothing matches.", "Faint"))
            self._body_layout.addStretch(1)
            return

        if searching:
            self._body_layout.addWidget(
                w.label(f"{len(options)} matching options", "Label"))
        else:
            for container in preamble:
                note = w.Card(container.path, flat=True)
                note.add(w.label(container.help, "Faint", wrap=True))
                self._body_layout.addWidget(note)
                self._body_layout.addWidget(w.spacer(12))

        for option in options:
            row = OptionRow(option, self.app.mode, self._body)
            self._body_layout.addWidget(row)
            self._rows.append(row)
        self._body_layout.addStretch(1)
        self._scroll.verticalScrollBar().setValue(0)
        self.recount()

    def recount(self) -> None:
        pending = [r for r in self._rows if r.changed]
        self._apply.setEnabled(bool(pending))
        self._revert.setEnabled(bool(pending))
        if pending:
            self._message.setText(
                f"{len(pending)} pending change"
                f"{'' if len(pending) == 1 else 's'} — nothing is written until "
                f"you apply.")
        else:
            self._message.setText("")

    # --- writing ----------------------------------------------------------

    def _apply_changes(self) -> None:
        pending = [r for r in self._rows if r.changed]
        if not pending:
            return
        edits = [(r, r.option.path, r.value()) for r in pending]
        self._apply.setEnabled(False)
        self._message.setText(f"Writing {len(edits)} change(s)…")

        def work() -> list[tuple[int, bool, str, Any]]:
            backup = self.hermes.backup_config()
            results: list[tuple[int, bool, str, Any]] = []
            for index, (_row, path, value) in enumerate(edits):
                if value is _UNSET:
                    outcome = self.hermes.config_unset(path)
                    results.append((index, outcome.ok, outcome.message, None))
                    continue
                outcome = self.hermes.config_set(path, value)
                results.append((index, outcome.ok, outcome.message, value))
            return [(len(results), bool(backup), str(backup or ""), None), *results]

        self.jobs.run(work, lambda r: self._applied(edits, r), self._failed)

    def _applied(self, edits, results) -> None:
        head, *rows = results
        _, had_backup, backup_path, _ = head
        failures = 0
        for index, ok, message, value in rows:
            row = edits[index][0]
            if ok:
                row.mark_saved(value)
            else:
                failures += 1
                row.mark_error(message)
        note = "backed up" if had_backup else "no backup taken"
        if failures:
            self._message.setText(
                f"{len(rows) - failures} written, {failures} rejected by Hermes "
                f"(see the rows marked above). Previous config {note}.")
        else:
            self._message.setText(
                f"{len(rows)} change(s) written to config.yaml. "
                f"Previous config {note}: {backup_path}")
        self.recount()

    def apply_mode(self, mode: str) -> None:
        super().apply_mode(mode)
        for row in self._rows:
            row.apply_mode(mode)
