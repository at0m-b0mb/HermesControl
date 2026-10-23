"""
App accounts, and the sign-in they all depend on.

Hermes can act on third-party apps — Linear, Notion, Slack, Stripe and some
fifty others — through what it calls *connectors*. Every one of them is
brokered by **Nous Portal**, so none of them work until the Portal account is
signed in. That single fact explains essentially every "the connectors are not
working" report, and nothing in the connector listing says it: each row just
reads ``not connected``, which looks like a per-app problem rather than one
missing sign-in.

So this module reports the Portal state first and the catalogue second.

It never performs a sign-in. Connecting an account is an OAuth flow in a real
browser against the user's own account, and that is theirs to complete — the
app opens it and reports what happened afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cli import Hermes, Result


@dataclass(frozen=True)
class Connector:
    """One app Hermes can be given access to."""

    name: str
    connected: bool

    @property
    def label(self) -> str:
        """A readable name: `clickhouse_mcp` is not what people call it."""
        stem = self.name.removesuffix("_mcp").replace("_", " ")
        return stem.title() if stem.islower() else stem


@dataclass
class Portal:
    """Whether the broker every connector depends on is signed in."""

    logged_in: bool = False
    model: str = ""
    web_tools: str = ""
    image_tools: str = ""
    raw: str = ""

    @property
    def blocks_connectors(self) -> bool:
        return not self.logged_in


class Connectors:
    """The `hermes connectors` and `hermes portal` surfaces, parsed."""

    def __init__(self, hermes: Hermes | None = None):
        self.hermes = hermes or Hermes()

    def portal(self) -> Portal:
        result = self.hermes.run(["portal", "status"], timeout=60)
        text = result.stdout + result.stderr
        state = Portal(raw=text)
        if match := re.search(r"Auth:\s*(.+)", text):
            answer = match.group(1).strip().lower()
            state.logged_in = "not logged in" not in answer
        if match := re.search(r"Model:\s*(.+)", text):
            state.model = match.group(1).strip()
        if match := re.search(r"Web tools\s+(.+)", text):
            state.web_tools = match.group(1).strip()
        if match := re.search(r"Image generation\s+(.+)", text):
            state.image_tools = match.group(1).strip()
        return state

    def catalogue(self) -> list[Connector]:
        """Every connector and whether it is connected.

        The listing is two columns of plain text. Anything that does not look
        like ``<name> <state>`` is a banner or a blank line and is skipped,
        rather than becoming a connector called "You".
        """
        result = self.hermes.run(["connectors", "list"], timeout=90)
        found: list[Connector] = []
        for line in result.stdout.splitlines():
            match = re.match(r"^\s*([a-z0-9_.-]+)\s{2,}(connected|not connected)\s*$",
                             line, re.IGNORECASE)
            if match:
                found.append(Connector(match.group(1),
                                       match.group(2).lower() == "connected"))
        return found

    def accounts(self) -> list[str]:
        result = self.hermes.run(["connectors", "accounts"], timeout=60)
        if "no connected accounts" in result.stdout.lower():
            return []
        return [line.strip() for line in result.stdout.splitlines()
                if line.strip() and not line.strip().startswith(("You", "-", "="))]

    def connect(self, app: str, alias: str = "") -> Result:
        """Start the browser sign-in for one app.

        Long timeout on purpose: the command waits for a browser round trip
        that a person has to complete, including a password and probably a
        second factor. Neither is ours to supply.
        """
        args = ["connectors", "connect", app]
        if alias:
            args += ["--alias", alias]
        return self.hermes.run(args, timeout=600)

    def disconnect(self, app: str) -> Result:
        return self.hermes.run(["connectors", "disconnect", app], timeout=120)

    def portal_login_hint(self) -> str:
        return "hermes portal"
