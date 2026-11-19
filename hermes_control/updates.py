"""
Keeping everything current — and saying which "everything" is which.

Four separate things here can be out of date, they are updated by four
different commands, and the version numbers look alike enough to be
confused for one another:

* **Hermes Agent** — ``hermes update``, on a release channel.
* **Hub skills** — ``hermes skills update``, per skill, from whichever
  registry each came from.
* **Plugins** — ``hermes plugins``, separately again.
* **This app** — a git checkout, updated by pulling it.

The failure this module exists to prevent is the quiet one: someone
reads "v1.10.0" in this window, concludes Hermes is current, and is
looking at the control panel's version rather than the agent's. Every
row here names what it is a version *of*.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

#: ``✓ Up to date with the latest release (stable v0.23.2 (ae2a81ccc00e)).``
#: ``→ Update available: v0.23.3``
_UP_TO_DATE = re.compile(r"up to date", re.IGNORECASE)
_AVAILABLE = re.compile(
    r"update available[^v\n]*v?(?P<version>[\w.]+)", re.IGNORECASE)
_LATEST = re.compile(r"latest release\s*\((?P<channel>\w+)\s+v?(?P<version>[\d.]+)")
_CHANNEL = re.compile(r"Update channel:\s*(?P<channel>\w+)", re.IGNORECASE)

#: ``0 update(s) available across 6 checked skill(s)``
_SKILL_COUNT = re.compile(
    r"(?P<n>\d+)\s+update\(s\)\s+available\s+across\s+(?P<checked>\d+)")


@dataclass
class Available:
    """What one updatable thing has to say for itself."""

    name: str
    installed: str = ""
    latest: str = ""
    channel: str = ""
    #: None when it could not be determined — which is different from
    #: "up to date" and must not be drawn as a reassuring tick.
    behind: bool | None = None
    detail: str = ""
    #: The command that would do something about it, for the button and
    #: for the person who would rather run it themselves.
    command: str = ""

    @property
    def state(self) -> str:
        if self.behind is None:
            return "unknown"
        return "behind" if self.behind else "current"


def parse_hermes_check(payload: str, installed: str = "",
                       ok: bool = True) -> Available:
    """Read ``hermes update --check``."""
    out = Available("Hermes Agent", installed=installed,
                    command="hermes update")
    if not ok:
        out.detail = payload.strip()[:300] or "The check could not be run."
        return out
    channel = _CHANNEL.search(payload)
    if channel:
        out.channel = channel.group("channel")
    latest = _LATEST.search(payload)
    if latest:
        out.latest = latest.group("version")
        out.channel = out.channel or latest.group("channel")
    available = _AVAILABLE.search(payload)
    if available:
        out.behind = True
        out.latest = out.latest or available.group("version")
        out.detail = f"Update available: v{out.latest}."
        return out
    if _UP_TO_DATE.search(payload):
        out.behind = False
        out.detail = (f"Up to date on the {out.channel or 'stable'} channel"
                      + (f" (v{out.latest})." if out.latest else "."))
        return out
    out.detail = payload.strip()[:300] or "No answer from the check."
    return out


def parse_skills_check(payload: str, ok: bool = True) -> Available:
    """Read ``hermes skills check``.

    Only *hub* skills are checked — the ones installed from a registry.
    Bundled skills travel with Hermes itself and a skill the agent wrote
    has no upstream to be behind, so a count here is never the whole
    library and the wording says so.
    """
    out = Available("Hub skills", command="hermes skills update")
    if not ok:
        out.detail = payload.strip()[:300] or "The check could not be run."
        return out
    found = _SKILL_COUNT.search(payload)
    if not found:
        out.detail = payload.strip()[-300:] or "No answer from the check."
        return out
    count = int(found.group("n"))
    checked = int(found.group("checked"))
    out.behind = count > 0
    out.detail = (
        f"{count} of {checked} hub skills have an update."
        if count else
        f"All {checked} hub skills that have an upstream are current. "
        f"Bundled skills travel with Hermes, and ones the agent wrote "
        f"have nothing to be behind.")
    return out


def compare_versions(installed: str, latest: str) -> bool | None:
    """Whether ``installed`` is older than ``latest``.

    Returns None rather than guessing when either side is missing or is
    not a plain dotted number — a wrong "update available" is worse than
    an honest "could not tell", because it sends someone to reinstall
    something that is already current.
    """
    def parts(v: str) -> tuple[int, ...] | None:
        v = v.strip().lstrip("vV")
        if not v or not re.fullmatch(r"\d+(\.\d+)*", v):
            return None
        return tuple(int(p) for p in v.split("."))

    a, b = parts(installed), parts(latest)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a < b
