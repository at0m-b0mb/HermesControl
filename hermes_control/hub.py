"""
The Skills Hub — Hermes's largest extension surface, and the one people
look for email in.

Hermes can be extended five different ways, and they are easy to confuse
because the documentation for each assumes you already know which one you
are in. Four of them are small, curated and already elsewhere in this app:
gateway platforms (messaging and email *inbound*), Portal connectors, the
MCP catalogue, and the skills that ship with an install.

The fifth is this one, and it is larger than the other four together:
``hermes skills search`` queries skills.sh, ClawHub, GitHub, and a dozen
provider registries at once. This is where Gmail, Outlook and the Himalaya
IMAP/SMTP skills live — none of which appear in the connector list or the
MCP catalogue, which is why looking there and finding nothing leads to the
reasonable but wrong conclusion that Hermes cannot touch your mailbox.

**Trust is the thing to keep in front of the user.** A skill is a
procedure the agent will follow, and some carry scripts it will run.
Hermes labels each result ``official``, ``verified`` or ``community`` and
scans before installing, refusing one it judges dangerous. This module
carries that label through rather than flattening every result into a row
that looks equally safe.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

#: Registries ``hermes skills search`` can be pointed at. "all" is the
#: default and the right one almost always; the rest are here because a
#: search for a common word returns a wall of near-duplicates, and naming
#: a source is the only way to cut it down.
SOURCES: tuple[str, ...] = (
    "all", "official", "skills-sh", "clawhub", "github", "well-known",
    "lobehub", "anthropic", "openai", "nvidia", "huggingface",
)

#: Searches worth offering as a starting point, because the question
#: "what can this thing actually do" has no good answer from an empty box.
#: Email leads because it is the one people ask for and cannot find.
STARTERS: tuple[tuple[str, str], ...] = (
    ("email", "Read, search and send from a real mailbox"),
    ("gmail", "Google's mail, through its own API"),
    ("outlook", "Microsoft 365 mail and calendar"),
    ("calendar", "Scheduling"),
    ("github", "Repositories, issues and pull requests"),
    ("notion", "Documents and databases"),
    ("spreadsheet", "Tabular data"),
    ("pdf", "Reading and writing documents"),
)

#: Mail skills worth naming outright, with what each one actually needs.
#: Chosen because they answer three different situations, and picking the
#: wrong one costs an hour: any IMAP mailbox, Gmail specifically, or
#: Microsoft 365.
#:
#: ``skill`` is the folder name once installed, so the page can tell the
#: difference between "you need this" and "you already have this and it
#: cannot run" — which are the same row with opposite advice. ``command``
#: is the binary the skill drives, and ``get`` installs that binary, not
#: the skill: Hermes ships the himalaya *skill* and not himalaya, so the
#: obvious reading of "already installed" is wrong in the one case people
#: are most likely to hit.
@dataclass(frozen=True)
class MailRoute:
    skill: str
    identifier: str
    what: str
    needs: str
    command: str = ""
    get: str = ""
    #: A shell command that walks the user through connecting an account.
    setup: str = ""
    #: What that step will ask for, so the page can warn about the one
    #: thing every major provider refuses: an ordinary account password.
    setup_note: str = ""


MAIL_ROUTES: tuple[MailRoute, ...] = (
    MailRoute(
        "himalaya", "himalaya-skill",
        "Any mailbox \u2014 Gmail, Outlook, iCloud",
        "Drives the himalaya CLI, which speaks IMAP and SMTP as well as "
        "Gmail's and Microsoft Graph's own APIs, so it reaches any provider "
        "and keeps the credentials on this machine.",
        command="himalaya",
        get="brew install himalaya",
        setup="himalaya",
        setup_note=(
            "Running himalaya with no account configured starts its setup "
            "wizard, which asks for your provider and address and puts the "
            "password in your system keyring. Gmail, Outlook, iCloud and "
            "Yahoo all refuse an ordinary account password here \u2014 create an "
            "app password first. The skill's own notes still mention "
            "'himalaya account configure', which this version removed.")),
    MailRoute(
        "gmail", "gmail-email", "Gmail, through Google's own API",
        "Reads, searches, drafts and replies using a Google sign-in rather "
        "than a password, so labels and threading work properly. Needs a "
        "Google Cloud OAuth client."),
    MailRoute(
        "outlook", "outlook-api", "Outlook and Microsoft 365",
        "Microsoft Graph with managed OAuth: mail, calendar and contacts. "
        "Needs an Azure app registration, or a work account whose admin has "
        "already made one."),
)


@dataclass
class Skill:
    name: str
    identifier: str
    source: str
    trust: str
    description: str

    @property
    def official(self) -> bool:
        return self.trust.lower() in ("official", "verified")


def parse_search(payload: str) -> list[Skill]:
    """Read ``hermes skills search --json``.

    The listing is the only machine-readable form; the table drops the
    second half of every identifier, which is the part needed to install.
    """
    try:
        rows = json.loads(payload)
    except (ValueError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[Skill] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("identifier") or row.get("name") or "").strip()
        if not identifier:
            continue
        out.append(Skill(
            name=str(row.get("name") or identifier),
            identifier=identifier,
            source=str(row.get("source") or ""),
            trust=str(row.get("trust_level") or row.get("trust") or ""),
            description=(str(row.get("description") or "").strip()),
        ))
    return out


def rank(skills: list[Skill]) -> list[Skill]:
    """Official first, then anything that bothered to describe itself.

    A large share of indexed results carry the placeholder "Indexed by
    skills.sh from <repo>", which says nothing about what the skill does.
    They are kept — one of them may be the right answer — but they do not
    deserve the top of the list.
    """
    def key(s: Skill) -> tuple:
        placeholder = s.description.lower().startswith("indexed by")
        return (not s.official, placeholder, s.name.lower())
    return sorted(skills, key=key)
