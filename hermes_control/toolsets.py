"""
Which tools a turn may use.

``hermes chat -t`` takes a comma-separated list of *individual* toolsets, or
the special value ``all``. It does **not** take the preset names from the
config (``hermes-cli``, ``hermes-telegram``): those are only valid under
``platform_toolsets``, and passing one to ``-t`` fails the turn with
``invalid_params`` a minute in.

That distinction is not written down anywhere, and neither is the list of
valid names — Hermes has no ``--list-toolsets``. Every name below was checked
against a live Hermes by running a turn with it, and
``tests/test_toolsets.py`` re-checks them, so a Hermes update that renames one
fails a test instead of failing a user's turn.

Names that look valid and are not: ``none`` and ``core`` (invented), and
``image`` and ``messaging``, which appear in the preset descriptions but are
rejected as standalone values.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Individual toolsets accepted by ``-t``, verified against Hermes v0.22.4.
VERIFIED: tuple[str, ...] = (
    "web", "terminal", "file", "vision", "tts",
    "browser", "skills", "todo", "cronjob", "memory",
)

#: Documented in the config's preset descriptions but rejected by ``-t``.
REJECTED_BY_CHAT: tuple[str, ...] = ("image", "messaging")


@dataclass(frozen=True)
class Choice:
    """One entry in the Console's tools selector."""

    label: str
    value: str | None       # None means "pass nothing and use the config"
    detail: str

    @property
    def names(self) -> list[str]:
        if not self.value or self.value == "all":
            return []
        return [part.strip() for part in self.value.split(",") if part.strip()]


#: What the Console offers. Deliberately a handful of intelligible choices
#: rather than ten checkboxes: the common need is "let it do everything" or
#: "do not let it touch my machine", and both are one click.
CHOICES: tuple[Choice, ...] = (
    Choice("As configured", None,
           "Whatever platform_toolsets sets for the CLI. The default."),
    Choice("Everything", "all",
           "Every tool this build has."),
    Choice("Nothing that writes", "web,vision,skills,todo",
           "Can read the web and look at images, but cannot run commands, "
           "write files or drive a browser."),
    Choice("Shell and files", "terminal,file,web",
           "Run commands and edit files. No browser, no image tools."),
    Choice("Web only", "web",
           "Fetch and search. Nothing local."),
)


def choice_for(label: str) -> Choice | None:
    for choice in CHOICES:
        if choice.label == label:
            return choice
    return None
