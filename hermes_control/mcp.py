"""
MCP servers: the way to give Hermes capabilities nobody shipped it with.

Hermes has four separate extension surfaces and they are easy to confuse.
*Connectors* are app accounts brokered by Nous Portal. *Skills* are markdown
procedures. *Plugins* change Hermes itself. And **MCP servers** are external
processes or endpoints exposing tools over the Model Context Protocol — which
is the one that adds genuinely new abilities, and the one with the largest
catalogue.

Worth stating plainly, because it is the first thing people look for:
**neither curated catalogue ships an email integration.** Not the Portal
connectors, not the MCP catalogue. Email comes from Hermes's own built-in
IMAP/SMTP gateway instead, which is a different thing in a different place.

The catalogue is Nous-approved, but ``mcp add`` takes any server, so the
ecosystem beyond it is reachable too — by URL for a hosted one, or by command
for a local one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cli import Hermes, Result


@dataclass(frozen=True)
class Server:
    """One MCP server, from the catalogue or already configured."""

    name: str
    status: str
    description: str = ""

    @property
    def installed(self) -> bool:
        return self.status.lower() not in ("available", "")

    @property
    def label(self) -> str:
        return self.name.replace("-", " ").replace("_", " ").title()


#: Rows the table has that are not servers.
_SKIP = {"name", "install:", "picker:", ""}


class Mcp:
    """The `hermes mcp` surface, parsed."""

    def __init__(self, hermes: Hermes | None = None):
        self.hermes = hermes or Hermes()

    def catalogue(self) -> list[Server]:
        """Every Nous-approved server, with whether it is configured.

        The output is a plain-text table. Anything that does not look like
        ``name  status  description`` is a header, a rule or a footer hint,
        and is skipped rather than becoming a server called "------".
        """
        result = self.hermes.run(["mcp", "catalog"], timeout=120)
        found: list[Server] = []
        for line in result.stdout.splitlines():
            match = re.match(
                r"^\s{2,}([a-z0-9][\w.-]*)\s{2,}(\S[^\s].*?)\s{2,}(\S.*)$", line)
            if not match:
                continue
            name, status, description = (g.strip() for g in match.groups())
            if name.lower() in _SKIP or set(name) <= {"-"}:
                continue
            found.append(Server(name, status, description))
        return found

    def configured(self) -> list[str]:
        """Servers this install already has."""
        result = self.hermes.run(["mcp", "list"], timeout=90)
        if "no mcp servers" in result.stdout.lower():
            return []
        names: list[str] = []
        for line in result.stdout.splitlines():
            match = re.match(r"^\s{2,}([a-z0-9][\w.-]*)\b", line)
            if match and match.group(1).lower() not in _SKIP:
                names.append(match.group(1))
        return names

    # --- changes -----------------------------------------------------------

    def install(self, name: str) -> Result:
        """Install a catalogue entry. May then need `login` for OAuth ones."""
        return self.hermes.run(["mcp", "install", name], timeout=300)

    def add_url(self, name: str, url: str, auth: str = "") -> Result:
        """Add a hosted server the catalogue does not carry."""
        args = ["mcp", "add", name, "--url", url]
        if auth:
            args += ["--auth", auth]
        return self.hermes.run(args, timeout=180)

    def add_command(self, name: str, command: str,
                    args_text: str = "") -> Result:
        """Add a local server run as a subprocess.

        ``--args`` must come last: it consumes the rest of the line, so
        anything after it is swallowed as an argument to the server.
        """
        args = ["mcp", "add", name, "--command", command]
        extra = [a for a in args_text.split() if a]
        if extra:
            args += ["--args", *extra]
        return self.hermes.run(args, timeout=180)

    def remove(self, name: str) -> Result:
        return self.hermes.run(["mcp", "remove", name], timeout=120)

    def test(self, name: str) -> Result:
        return self.hermes.run(["mcp", "test", name], timeout=180)

    def login(self, name: str) -> Result:
        """Re-run OAuth for a server that needs it. Opens a browser."""
        return self.hermes.run(["mcp", "login", name], timeout=600)


#: Where each kind of capability actually comes from. The question "why is
#: there no email connector" has a real answer, and it is not in either
#: catalogue.
WHERE_THINGS_LIVE = (
    ("Email", "Hermes's own IMAP/SMTP gateway — the Gateway page, not a "
              "connector. Neither catalogue ships an email integration."),
    ("Messaging", "Gateway platforms: Telegram, Discord, Slack, WhatsApp, "
                  "Signal. Also the Gateway page."),
    # No counts here. They drift the moment either catalogue changes, and a
    # stale number in a card that exists to orient people is worse than none;
    # each page shows its own live count in the header.
    ("App accounts", "Portal connectors, brokered by Nous Portal — the "
                     "Connectors page."),
    ("New tools", "MCP servers — this page. The catalogue is Nous-approved, "
                  "and `add` takes any server beyond it."),
    ("Procedures", "Skills: markdown the agent can load, including ones it "
                   "writes itself."),
)
