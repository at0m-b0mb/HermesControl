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
import subprocess
from dataclasses import dataclass

from . import platforms
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

    def sign_in_stream(self):
        """Run the sign-in, yielding each line as it is printed.

        This has to stream. ``auth upgrade`` is a device-code flow: it prints
        a URL and a short code, then blocks waiting for the person to use
        them. Capturing the output and returning it at the end — which is
        what a plain run does — means the code only appears once the flow has
        already finished or timed out, so a window driving it would show
        nothing at all while the user waited for something to look at.
        """
        argv = [str(self.hermes.install.executable), "auth", "upgrade"]
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            env=self.hermes.env(),
            creationflags=0x08000000 if platforms.IS_WINDOWS else 0,
        )
        self._proc = proc
        if proc.stdout is not None:
            for line in proc.stdout:
                yield line.rstrip()
        proc.wait()
        self._proc = None

    def cancel_sign_in(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    @staticmethod
    def extract_code(text: str) -> tuple[str, str]:
        """Pull the URL and the short code out of the flow's own output."""
        url = re.search(r"(https://\S*portal\.nousresearch\.com\S*)", text)
        code = re.search(r"enter code:\s*([A-Z0-9-]{4,})", text, re.IGNORECASE)
        if code is None:
            code = re.search(r"\bcode=([A-Z0-9-]{4,})", text)
        return (url.group(1) if url else "", code.group(1) if code else "")

    def sign_in(self, timeout: float = 600.0) -> Result:
        """Start the Nous Portal OAuth flow, which opens a browser.

        Not ``hermes portal``. That command is interactive onboarding, and
        without a terminal it degrades to an informational banner, prints the
        real instruction in prose, and **exits 0** — so a button wired to it
        reports success and does nothing, which is exactly what happened.

        ``hermes auth upgrade`` is the non-interactive entry point and opens
        the browser itself unless told not to. The long timeout is deliberate:
        it waits on a person completing a sign-in, possibly with a second
        factor.
        """
        return self.hermes.run(["auth", "upgrade"], timeout=timeout)

    def open_signup(self) -> Result:
        """Open the Portal subscription page, for someone with no account."""
        return self.hermes.run(["portal", "open"], timeout=60)

    def signed_in(self) -> bool:
        """Ask again, rather than trusting a command's exit code."""
        return self.portal().logged_in

    def portal_login_hint(self) -> str:
        return "hermes auth upgrade"
