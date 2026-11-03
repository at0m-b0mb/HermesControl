"""
MCP — giving Hermes tools nobody shipped it with.

This page exists because of a question with a genuinely useful answer: *why
is there no email connector?* Hermes has four extension surfaces that are
easy to confuse, and the thing you want is rarely on the one you are looking
at. So the page opens by saying where each kind of capability actually comes
from, and only then lists the catalogue.

Installing a server is not the same as being signed in to it. Many of these
are hosted and need an OAuth round trip afterwards, which is a browser flow
against the user's own account — the page starts it and reports; it never
handles those credentials.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget

from ...mcp import WHERE_THINGS_LIVE, Mcp
from .. import widgets as w
from ..shell import Page


class McpPage(Page):
    title = "MCP"
    group = "Automation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._mcp = Mcp(self.hermes)
        self._catalogue: list = []
        self._configured: list[str] = []
        self._busy = ""

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(16)

        header = w.PageHeader(
            "Automation", "MCP",
            "Servers that expose tools to Hermes over the Model Context "
            "Protocol. This is how it gains abilities it did not ship with.")
        self._count = w.label("", "Faint")
        header.add_action(self._count)
        header.add_action(w.button("Rescan", "", self.refresh))
        layout.addWidget(header)

        # The orientation card. Four extension surfaces is three too many to
        # keep straight, and "where is email" is the question everyone asks.
        guide = w.Card("Where capabilities come from", accent=True)
        table = w.KeyValue()
        for name, detail in WHERE_THINGS_LIVE:
            table.add(name, detail)
        guide.add(table)
        layout.addWidget(guide)

        self._filter = QLineEdit()
        self._filter.setObjectName("Search")
        self._filter.setPlaceholderText("Filter the catalogue")
        self._filter.textChanged.connect(lambda _: self._render())
        layout.addWidget(self._filter)

        self._list_card = w.Card("Catalogue")
        self._list_box = QVBoxLayout()
        self._list_box.setSpacing(3)
        self._list_card.add_layout(self._list_box)
        layout.addWidget(self._list_card)

        # Anything outside the catalogue.
        custom = w.Card("Add a server the catalogue does not have")
        custom.add(w.label(
            "The catalogue is Nous-approved, not exhaustive. Any MCP server "
            "can be added: a hosted one by URL, a local one by the command "
            "that runs it.", "Faint", wrap=True))
        self._name = QLineEdit()
        self._name.setPlaceholderText("name, e.g. my-gmail")
        self._name.setFixedWidth(200)
        self._kind = QComboBox()
        self._kind.addItems(["Hosted (URL)", "Local (command)"])
        self._kind.setFixedWidth(170)
        self._target = QLineEdit()
        self._target.setPlaceholderText("https://example.com/mcp")
        self._kind.currentTextChanged.connect(self._kind_changed)
        self._auth = QComboBox()
        self._auth.addItems(["no auth", "oauth", "header"])
        self._auth.setFixedWidth(120)
        custom.add(w.row(self._name, self._kind, self._target, self._auth,
                         w.button("Add", "Primary", self._add)))
        layout.addWidget(custom)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    # --- data ---------------------------------------------------------------

    def refresh(self) -> None:
        if self._busy:
            return
        self._mcp = Mcp(self.hermes)
        self._message.setText("Reading the MCP catalogue…")
        self.jobs.run(self._gather, self._show, self._failed)

    def _gather(self) -> dict:
        if not self.hermes.installed:
            return {"installed": False}
        return {"installed": True,
                "catalogue": self._mcp.catalogue(),
                "configured": self._mcp.configured()}

    def _show(self, data: dict) -> None:
        if not data.get("installed"):
            self._message.setText("Install Hermes Agent from Setup first.")
            return
        self._catalogue = data["catalogue"]
        self._configured = data["configured"]
        self._count.setText(
            f"{len(self._catalogue)} available · {len(self._configured)} configured")
        self._render()
        self.apply_mode(self.app.mode)

    def _render(self) -> None:
        self._clear(self._list_box)
        query = self._filter.text().strip().lower()
        shown = [s for s in self._catalogue
                 if not query or query in s.name.lower()
                 or query in s.description.lower()]
        if not shown:
            self._list_box.addWidget(w.label(
                "Nothing matches. The catalogue is Nous-approved — use the box "
                "below for anything else.", "Faint", wrap=True))
            return
        mode = self.app.mode
        for server in shown[:90]:
            on = server.name in self._configured
            name = w.label(server.name, "Mono")
            name.setFixedWidth(170)
            badge = w.Badge("CONFIGURED" if on else "AVAILABLE",
                            "live" if on else "idle")
            badge.apply_mode(mode)
            desc = w.label(server.description, "Faint", wrap=True)
            if on:
                action = w.button("Remove", "Quiet",
                                  lambda n=server.name: self._act("remove", n))
                check = w.button("Test", "Quiet",
                                 lambda n=server.name: self._act("test", n))
            else:
                action = w.button("Install", "",
                                  lambda n=server.name: self._act("install", n))
                check = w.spacer(1)
            action.setFixedWidth(92)
            row = w.row(name, badge, desc, check, action, stretch_last=False)
            row.layout().setStretch(2, 1)
            self._list_box.addWidget(row)
        if len(shown) > 90:
            self._list_box.addWidget(w.label(
                f"{len(shown) - 90} more — use the filter.", "Faint"))

    def _failed(self, error: str) -> None:
        self._busy = ""
        self._message.setText(f"Could not read MCP servers: {error}")

    # --- actions ------------------------------------------------------------

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _kind_changed(self, label: str) -> None:
        hosted = label.startswith("Hosted")
        self._target.setPlaceholderText(
            "https://example.com/mcp" if hosted else "npx")
        self._auth.setEnabled(hosted)

    def _act(self, what: str, name: str) -> None:
        self._busy = name
        verb = {"install": "Installing", "remove": "Removing",
                "test": "Testing"}[what]
        self._message.setText(f"{verb} {name}…")
        runner = {"install": self._mcp.install, "remove": self._mcp.remove,
                  "test": self._mcp.test}[what]
        self.jobs.run(lambda: runner(name),
                      lambda r: self._after(r, f"{what} {name}"), self._failed)

    def _add(self) -> None:
        name = self._name.text().strip()
        target = self._target.text().strip()
        if not name or not target:
            self._message.setText("A name and a URL or command are needed.")
            return
        hosted = self._kind.currentText().startswith("Hosted")
        auth = self._auth.currentText()
        self._busy = name
        self._message.setText(f"Adding {name}…")

        def work():
            if hosted:
                return self._mcp.add_url(
                    name, target, "" if auth == "no auth" else auth)
            parts = target.split()
            return self._mcp.add_command(name, parts[0], " ".join(parts[1:]))

        self.jobs.run(work, lambda r: self._after(r, f"add {name}"), self._failed)

    def _after(self, result, what: str) -> None:
        self._busy = ""
        head = (result.stdout or result.stderr or "").strip().splitlines()
        summary = next((line.strip() for line in head if line.strip()), "")
        if result.ok:
            self._name.clear()
            self._target.clear()
            self._message.setText(
                f"{what}: done. {summary[:140]}"
                + ("  A hosted server may still need signing in to — use "
                   "Test, and if it refuses, run `hermes mcp login "
                   f"{what.split()[-1]}`." if what.startswith(("install", "add"))
                   else ""))
        else:
            self._message.setText(f"{what}: {result.message}")
        self.refresh()
