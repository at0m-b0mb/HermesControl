"""
Pooled provider credentials — what is actually signed in.

The Models page used to decide a hosted provider's state like this::

    have = provider.credential in secrets if provider.credential else provider.oauth

For a key-based provider that works. For an **OAuth** one — Nous Portal,
OpenAI Codex — ``provider.credential`` is empty, so the expression
collapses to ``provider.oauth``, which is ``True`` by definition. The row
therefore showed a live "OAUTH" badge and an enabled **Use** button
whether or not anyone had ever signed in, and offered no way to sign in
at all. Pressing Use set ``model.provider`` to a provider with no
credential behind it, and every turn afterwards failed somewhere else
entirely.

``hermes auth list`` is the real answer. It prints the credential pool
that Hermes will actually draw on::

    copilot (1 credentials):
      #1  gh auth token        api_key id=b7866d priority=0 gh_cli ←

    nous (1 credentials):
      #1  you@example.com      oauth   id=095dbe priority=0 device_code ←

A provider absent from that listing has nothing behind it, whatever is
sitting in ``.env``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

#: ``provider (N credentials):`` — the header of each block.
_HEADER = re.compile(r"^(?P<provider>[\w.\-]+)\s*\((?P<count>\d+)\s+credential")
#: ``#1  label   kind   id=xxxx priority=0 source ←``. The label can contain
#: spaces (it is often an email or "gh auth token"), so the kind is found by
#: name rather than by column.
_ENTRY = re.compile(
    r"^\s*#(?P<index>\d+)\s+(?P<rest>.*)$")
_KIND = re.compile(r"\b(oauth|api_key|api-key)\b")
_ID = re.compile(r"\bid=(?P<id>\w+)")


@dataclass
class Credential:
    provider: str
    index: int
    label: str
    kind: str
    ident: str = ""
    active: bool = False

    @property
    def is_oauth(self) -> bool:
        return self.kind.replace("-", "_") == "oauth"


@dataclass
class Pool:
    credentials: list[Credential] = field(default_factory=list)
    #: False when the listing could not be read at all, in which case the
    #: page must say so rather than report every provider as signed out.
    read: bool = False
    error: str = ""

    def for_provider(self, key: str) -> list[Credential]:
        return [c for c in self.credentials if c.provider == key]

    def has(self, key: str) -> bool:
        return bool(self.for_provider(key))

    @property
    def providers(self) -> list[str]:
        seen: list[str] = []
        for c in self.credentials:
            if c.provider not in seen:
                seen.append(c.provider)
        return seen


def parse_list(payload: str) -> list[Credential]:
    """Read ``hermes auth list``.

    There is no ``--json`` on this subcommand, so the table is all there
    is. Parsed defensively: an unrecognised line is skipped rather than
    throwing away the block it sits in.
    """
    out: list[Credential] = []
    provider = ""
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _HEADER.match(stripped)
        if header:
            provider = header.group("provider")
            continue
        entry = _ENTRY.match(line)
        if not entry or not provider:
            continue
        rest = entry.group("rest")
        kind_match = _KIND.search(rest)
        kind = kind_match.group(1) if kind_match else ""
        # Everything before the kind is the label; it may contain spaces.
        label = (rest[:kind_match.start()] if kind_match else rest).strip()
        ident = (_ID.search(rest).group("id")
                 if _ID.search(rest) else "")
        out.append(Credential(
            provider=provider, index=int(entry.group("index")),
            label=label, kind=kind, ident=ident,
            # The arrow marks the credential Hermes will reach for first.
            active="←" in rest or "<-" in rest))
    return out


def pool(payload: str, read: bool, error: str = "") -> Pool:
    return Pool(credentials=parse_list(payload) if read else [],
                read=read, error=error)


#: Providers whose sign-in is a device code rather than a key, with the
#: argument ``hermes auth add`` wants. ``nous`` is upgraded rather than
#: added, because ``auth upgrade`` is the entry point that keeps any
#: connectors already attached to the account.
OAUTH_COMMAND: dict[str, list[str]] = {
    "nous": ["auth", "upgrade"],
    "openai-codex": ["auth", "add", "openai-codex", "--type", "oauth",
                     "--no-browser"],
}


def sign_in_argv(provider: str) -> list[str]:
    """The command that signs this provider in.

    ``--no-browser`` is deliberate for anything but Nous: the flow then
    prints its URL and code instead of opening a browser and printing
    nothing, and printed is the only form a window can show.
    """
    return OAUTH_COMMAND.get(
        provider,
        ["auth", "add", provider, "--type", "oauth", "--no-browser"])


#: A device-code flow prints a URL and a short code and then blocks. Both
#: are worth pulling out of the stream and showing large, because they are
#: the only two things the user has to act on.
_URL = re.compile(r"(https?://\S+)")
_CODE = re.compile(
    r"(?:enter\s+code|user[\s_-]?code|code)\s*[:=]\s*([A-Z0-9][A-Z0-9-]{3,})",
    re.IGNORECASE)


def extract_code(text: str) -> tuple[str, str]:
    """Pull the verification URL and short code out of a flow's output."""
    url = _URL.search(text)
    code = _CODE.search(text)
    if code is None:
        # Some flows print the code alone on its own line, spaced out.
        bare = re.search(r"^\s*([A-Z0-9]{4}-[A-Z0-9]{4})\s*$", text,
                         re.MULTILINE)
        code = bare
    return (url.group(1).rstrip(".,)") if url else "",
            code.group(1) if code else "")
