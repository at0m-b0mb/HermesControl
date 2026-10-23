"""
Contrast tests for the palette.

Every text pairing the interface actually uses, checked against WCAG AA in
both themes. This is not ceremony: mid-grey on true black passes the eye and
fails the maths, and the reverse happens on warm paper too.

AA wants 4.5:1 for body text and 3:1 for large text (>=24px or bold >=19px).
Secondary text on true black is held to a higher bar than AA because AA is a
floor and washed-out grey still reads as washed out at 8:1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import theme  # noqa: E402

AA_BODY = 4.5
AA_LARGE = 3.0
#: Secondary ink on a dark ground gets a stricter floor than AA. See module docstring.
DARK_SECONDARY_FLOOR = 7.0

MODES = (theme.LIGHT, theme.DARK)

#: (ink token, ground token, minimum ratio, what it is)
TEXT_PAIRS = [
    ("ink", "canvas", AA_BODY, "body text on the desk"),
    ("ink", "surface", AA_BODY, "body text on a card"),
    ("ink", "surface_alt", AA_BODY, "body text in a well"),
    ("ink", "sunken", AA_BODY, "body text on a sunken ground"),
    ("ink", "rail", AA_BODY, "navigation label"),
    ("ink_muted", "canvas", AA_BODY, "secondary text on the desk"),
    ("ink_muted", "surface", AA_BODY, "secondary text on a card"),
    ("ink_muted", "surface_alt", AA_BODY, "secondary text in a well"),
    ("ink_muted", "rail", AA_BODY, "inactive navigation item"),
    ("ink_faint", "canvas", AA_LARGE, "caption on the desk"),
    ("ink_faint", "surface", AA_LARGE, "caption on a card"),
    ("ink_faint", "rail", AA_LARGE, "rail group heading"),
    ("ink_faint", "surface_alt", AA_LARGE, "hint in a well"),
    # The brass is the one gold allowed to carry words.
    ("brass", "canvas", AA_BODY, "eyebrow above a page title"),
    ("brass", "surface", AA_BODY, "accent text on a card"),
    ("brass", "brass_wash", AA_BODY, "accent text on its own wash"),
    ("brass", "surface_alt", AA_BODY, "link in a well"),
    # Button fills: the label sits on the accent, not beside it.
    ("ink_inverse", "brass", AA_BODY, "primary button label"),
    # State text on its matching wash.
    ("live", "live_wash", AA_BODY, "running state"),
    ("live", "surface", AA_BODY, "running state on a card"),
    ("attention", "attention_wash", AA_BODY, "needs-attention state"),
    ("attention", "surface", AA_BODY, "needs-attention on a card"),
    ("fault", "fault_wash", AA_BODY, "fault state"),
    ("fault", "surface", AA_BODY, "fault on a card"),
    ("idle", "idle_wash", AA_LARGE, "idle state"),
    ("idle", "surface", AA_BODY, "idle on a card"),
    # Where a model runs.
    ("local", "surface", AA_BODY, "local model badge"),
    ("remote", "surface", AA_BODY, "remote model badge"),
    ("local", "surface_alt", AA_BODY, "local badge in a well"),
    ("remote", "surface_alt", AA_BODY, "remote badge in a well"),
    # Mono text in the config editor.
    ("ink", "sunken", AA_BODY, "config key in the gutter"),
    ("ink_muted", "sunken", AA_BODY, "config comment in the gutter"),
]

#: Marks that carry no words still have to be visible against their ground.
MARK_PAIRS = [
    ("shine", "rail", 1.8, "active navigation bar"),
    ("shine", "canvas", 1.8, "hairline under the wordmark"),
    ("shine", "surface", 1.8, "selected tab underline"),
    ("rule", "canvas", 1.12, "hairline on the desk"),
    ("rule", "surface", 1.12, "hairline on a card"),
    ("rule_strong", "surface", 1.3, "input border"),
    ("rule_strong", "canvas", 1.2, "input border on the desk"),
    ("focus", "surface", 2.0, "focus ring"),
]


def _ratio(ink: str, ground: str, mode: str) -> float:
    return theme.contrast(theme.color(ink, mode), theme.color(ground, mode))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("ink,ground,floor,what", TEXT_PAIRS,
                         ids=[f"{p[0]}-on-{p[1]}" for p in TEXT_PAIRS])
def test_text_contrast(mode: str, ink: str, ground: str, floor: float, what: str) -> None:
    ratio = _ratio(ink, ground, mode)
    assert ratio >= floor, (
        f"{what}: {ink} on {ground} in {mode} is {ratio:.2f}:1, "
        f"below the {floor}:1 floor "
        f"({theme.color(ink, mode)} on {theme.color(ground, mode)})"
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("ink,ground,floor,what", MARK_PAIRS,
                         ids=[f"{p[0]}-on-{p[1]}" for p in MARK_PAIRS])
def test_mark_visibility(mode: str, ink: str, ground: str, floor: float, what: str) -> None:
    ratio = _ratio(ink, ground, mode)
    assert ratio >= floor, (
        f"{what}: {ink} on {ground} in {mode} is only {ratio:.2f}:1, "
        f"below the {floor}:1 floor"
    )


@pytest.mark.parametrize("ink,ground", [("ink_muted", "canvas"),
                                        ("ink_muted", "surface"),
                                        ("ink_faint", "surface")])
def test_dark_secondary_is_not_washed_out(ink: str, ground: str) -> None:
    """AA is a floor, not the goal — on true black, grey needs more."""
    ratio = _ratio(ink, ground, theme.DARK)
    assert ratio >= DARK_SECONDARY_FLOOR, (
        f"{ink} on {ground} in dark is {ratio:.2f}:1; the floor for secondary "
        f"ink on a near-black ground is {DARK_SECONDARY_FLOOR}:1"
    )


def test_dark_mode_is_true_black() -> None:
    assert theme.color("canvas", theme.DARK) == "#000000"


def test_nothing_in_the_dark_ramp_reads_as_blue() -> None:
    """They rejected dark-navy explicitly: blue must never dominate."""
    for name, pair in theme.PALETTE.items():
        hexv = pair.dark.lstrip("#")
        r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
        if name == "remote":
            continue  # the one deliberate violet, and it is a badge not a ground
        assert b <= max(r, g) + 6, (
            f"dark token {name} ({pair.dark}) is blue-dominant: "
            f"r={r} g={g} b={b}"
        )


def test_every_colour_declares_both_halves() -> None:
    for name, pair in theme.PALETTE.items():
        assert pair.light.startswith("#") and len(pair.light) == 7, name
        assert pair.dark.startswith("#") and len(pair.dark) == 7, name


def test_two_golds_are_actually_different() -> None:
    """One gold cannot be small text and a bright mark at the same time."""
    for mode in MODES:
        brass = theme.color("brass", mode)
        shine = theme.color("shine", mode)
        assert brass != shine
        on_ground = _ratio("brass", "canvas", mode)
        assert on_ground >= AA_BODY, f"brass must stay legible in {mode}"


def test_stylesheet_builds_for_every_mode() -> None:
    for mode in MODES:
        qss = theme.stylesheet(mode)
        assert "{{" not in qss and "}}" not in qss, "unescaped brace in QSS"
        assert len(qss) > 4000

#: Every button variant that overrides colour with an ID selector. Qt ranks an
#: ID above a pseudo-state on a bare type selector, so `QPushButton:disabled`
#: does not reach them — without their own rule they keep enabled colours
#: while being unclickable, which reads as "broken" rather than "not yet".
ID_BUTTONS = ("Primary", "Danger", "Quiet", "Link")


@pytest.mark.parametrize("name", ID_BUTTONS)
@pytest.mark.parametrize("mode", MODES)
def test_every_id_button_styles_its_disabled_state(name: str, mode: str) -> None:
    qss = theme.stylesheet(mode)
    assert f"QPushButton#{name} " in qss or f"QPushButton#{name}{{" in qss
    assert f"QPushButton#{name}:disabled" in qss, (
        f"a disabled #{name} button would keep its enabled colours")


@pytest.mark.parametrize("mode", MODES)
def test_disabled_text_is_distinguishable_from_enabled(mode: str) -> None:
    """Disabled ink must differ from body ink, or the state is invisible."""
    assert theme.color("ink_faint", mode) != theme.color("ink", mode)
    ratio = theme.contrast(theme.color("ink_faint", mode),
                           theme.color("surface_alt", mode))
    assert ratio >= AA_LARGE, f"disabled text is unreadable at {ratio:.2f}:1"
