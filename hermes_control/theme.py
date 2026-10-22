"""
The design system.

One place for every colour, typeface and measurement, so Hermes Control looks
designed rather than assembled. Nothing here draws anything — a widget asks
for a token and gets a value.

Two rules hold the palette together. Every colour is declared as a
``(light, dark)`` pair at the point of definition, so there is no way to add
one and forget the dark theme. And there are two golds, not one: a deep brass
that stays legible as small text, and a bright shine used only on marks that
carry no words.

Dark mode is true black — ``#000000`` — with neutral greys above it and
nothing in the ramp that reads as blue.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

_IS_MAC = platform.system() == "Darwin"
_IS_WIN = platform.system() == "Windows"

LIGHT = "light"
DARK = "dark"
AUTO = "auto"


# --- typefaces --------------------------------------------------------------
# A serif for identity and figures, a neutral sans for controls, a mono for
# config keys and the agent's raw output. That mix is most of the effect.

# Each role is an ordered list of candidates rather than one name plus a CSS
# fallback string. Qt cannot see several of the fonts a platform nominally
# has — on macOS it reports Iowan Old Style, SF Pro Text and SF Mono as
# missing even though the OS uses them — and a stylesheet quietly falls back
# while ``QFont`` does not. Painted widgets would then be set in something
# nobody chose. So the stack drives CSS and the *resolved* first-present
# family drives QFont, and the two agree.

if _IS_MAC:
    SERIF_CHOICES = ["Iowan Old Style", "Palatino", "Georgia"]
    SANS_CHOICES = ["SF Pro Text", "Helvetica Neue", "Arial"]
    MONO_CHOICES = ["SF Mono", "Menlo", "Monaco"]
    SERIF_LAST, SANS_LAST, MONO_LAST = "serif", "sans-serif", "monospace"
elif _IS_WIN:
    SERIF_CHOICES = ["Georgia", "Times New Roman"]
    SANS_CHOICES = ["Segoe UI Variable Text", "Segoe UI", "Tahoma", "Arial"]
    MONO_CHOICES = ["Cascadia Mono", "Consolas", "Courier New"]
    SERIF_LAST, SANS_LAST, MONO_LAST = "serif", "sans-serif", "monospace"
else:
    SERIF_CHOICES = ["DejaVu Serif", "Liberation Serif", "Times New Roman"]
    SANS_CHOICES = ["Inter", "DejaVu Sans", "Liberation Sans", "Cantarell"]
    MONO_CHOICES = ["DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono"]
    SERIF_LAST, SANS_LAST, MONO_LAST = "serif", "sans-serif", "monospace"


def _stack(choices: list[str], generic: str) -> str:
    return ", ".join(f'"{name}"' for name in choices) + f", {generic}"


SERIF_STACK = _stack(SERIF_CHOICES, SERIF_LAST)
SANS_STACK = _stack(SANS_CHOICES, SANS_LAST)
MONO_STACK = _stack(MONO_CHOICES, MONO_LAST)

_resolved: dict[str, str] = {}


def _available(choices: list[str]) -> str:
    """The first candidate Qt can actually render, or the first as a guess.

    Needs no QApplication: without one it returns the preferred name, which is
    what the dependency-free tests want.
    """
    key = choices[0]
    if key in _resolved:
        return _resolved[key]
    chosen = choices[0]
    try:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            families = set(QFontDatabase.families())
            chosen = next((name for name in choices if name in families), choices[-1])
    except Exception:
        pass
    _resolved[key] = chosen
    return chosen


# Preferred names, kept for display (the colophon names what it is set in).
SERIF, SANS, MONO = SERIF_CHOICES[0], SANS_CHOICES[0], MONO_CHOICES[0]


def serif() -> str:
    return _available(SERIF_CHOICES)


def sans() -> str:
    return _available(SANS_CHOICES)


def mono() -> str:
    return _available(MONO_CHOICES)

TYPE = {
    "wordmark":   (SERIF_STACK, 22, 600),
    "display":    (SERIF_STACK, 30, 400),
    "page_title": (SERIF_STACK, 23, 400),
    "figure":     (SERIF_STACK, 40, 400),
    "figure_sm":  (SERIF_STACK, 22, 400),
    "card_title": (SANS_STACK, 13, 650),
    "subtitle":   (SANS_STACK, 12, 400),
    "body":       (SANS_STACK, 13, 400),
    "body_bold":  (SANS_STACK, 13, 650),
    "small":      (SANS_STACK, 11, 400),
    "small_bold": (SANS_STACK, 11, 650),
    "label":      (SANS_STACK, 10, 650),
    "mono":       (MONO_STACK, 12, 400),
    "mono_small": (MONO_STACK, 11, 400),
    "editor":     (MONO_STACK, 13, 400),
}

SPACE = {"hair": 2, "tight": 4, "snug": 8, "base": 12, "roomy": 16,
         "wide": 24, "gutter": 32, "page": 40}

RADIUS = {"sharp": 0, "small": 3, "card": 6, "pill": 999}


# --- colour -----------------------------------------------------------------

@dataclass(frozen=True)
class Pair:
    light: str
    dark: str

    def get(self, mode: str) -> str:
        return self.dark if mode == DARK else self.light


PALETTE: dict[str, Pair] = {
    # grounds
    "canvas":        Pair("#F3F1EC", "#000000"),
    "surface":       Pair("#FFFFFF", "#131312"),
    "surface_alt":   Pair("#FAF8F4", "#1B1B19"),
    "sunken":        Pair("#EBE7DE", "#0A0A09"),
    "rail":          Pair("#EDEAE2", "#0B0B0A"),

    # lines
    "rule":          Pair("#DCD6C9", "#2B2B28"),
    "rule_strong":   Pair("#C4BCAA", "#3D3C38"),

    # ink. The dark halves sit high on purpose: a mid-grey passes AA on true
    # black and still reads as washed out.
    "ink":           Pair("#1B1813", "#F3F0E9"),
    "ink_muted":     Pair("#575144", "#B8B2A6"),
    "ink_faint":     Pair("#6B6554", "#A6A096"),
    "ink_inverse":   Pair("#FFFFFF", "#0A0A09"),

    # gold, twice over
    "brass":         Pair("#7A5D18", "#D9B75C"),   # legible as text
    "shine":         Pair("#C39B24", "#F1C84B"),   # marks only, never text
    "brass_wash":    Pair("#F7F0DC", "#221D0E"),
    "brass_edge":    Pair("#E3D4A5", "#463A1A"),

    # selection and focus
    "select":        Pair("#E6DFCB", "#2A2519"),
    "focus":         Pair("#7A5D18", "#D9B75C"),

    # state — what a process or a check can be saying
    "live":          Pair("#2C6249", "#67BE94"),
    "live_wash":     Pair("#E9F3ED", "#0D1F16"),
    "idle":          Pair("#6B6554", "#9A948A"),
    "idle_wash":     Pair("#F1EFE9", "#161613"),
    "attention":     Pair("#8A5410", "#DDA356"),
    "attention_wash": Pair("#FAF0DF", "#251A0B"),
    "fault":         Pair("#8C1F16", "#EE8B82"),
    "fault_wash":    Pair("#FBE9E7", "#2A100E"),

    # where a model runs — the one distinction the Models page is built on
    "local":         Pair("#2C6249", "#67BE94"),
    "remote":        Pair("#5A4A7A", "#B0A0D0"),
}


def color(name: str, mode: str) -> str:
    return PALETTE[name].get(mode)


def font_css(role: str) -> str:
    """CSS for a role, with the family Qt can really render named first.

    Qt scans — and warns about — every missing family it meets before a usable
    one, which costs real milliseconds at startup. Leading with the resolved
    name avoids the scan while keeping the rest of the stack for other hosts.
    """
    family, size, weight = TYPE[role]
    if family == SERIF_STACK:
        resolved, generic = serif(), SERIF_LAST
    elif family == MONO_STACK:
        resolved, generic = mono(), MONO_LAST
    else:
        resolved, generic = sans(), SANS_LAST
    return (f'font-family: "{resolved}", {generic}; '
            f"font-size: {size}px; font-weight: {weight};")


def font(role: str):
    """A QFont for a role, for the places QSS cannot reach (painted widgets).

    Resolves to a family Qt can really render, so a painted widget is never
    silently set in the system default while the rest of the page is not.
    """
    from PySide6.QtGui import QFont
    family, size, weight = TYPE[role]
    if family == SERIF_STACK:
        name = serif()
    elif family == MONO_STACK:
        name = mono()
    else:
        name = sans()
    qf = QFont(name, size)
    qf.setWeight(QFont.Weight.DemiBold if weight >= 600 else QFont.Weight.Normal)
    return qf


def resolve(mode: str) -> str:
    """Turn AUTO into a real mode by asking the platform."""
    if mode != AUTO:
        return mode
    try:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            window = app.palette().color(QPalette.ColorRole.Window)
            return DARK if window.lightness() < 128 else LIGHT
    except Exception:
        pass
    return LIGHT


def state_token(state: str) -> str:
    """Which colour family a runtime state wears."""
    return {
        "running": "live", "ready": "live", "ok": "live", "pass": "live",
        "stopped": "idle", "absent": "idle", "unset": "idle", "idle": "idle",
        "starting": "attention", "stale": "attention", "warn": "attention",
        "error": "fault", "failed": "fault", "missing": "fault",
    }.get(state, "idle")


# --- stylesheet -------------------------------------------------------------

def stylesheet(mode: str) -> str:
    """The whole application's QSS, built from the tokens above."""
    c = lambda n: color(n, mode)  # noqa: E731
    s = SPACE
    on_shine = "#1B1813"

    return f"""
QWidget {{ background: transparent; color: {c('ink')}; {font_css('body')} }}
QMainWindow, #PageHost, QDialog {{ background: {c('canvas')}; }}

/* --- the rail ------------------------------------------------------------ */
#Rail {{ background: {c('rail')}; border-right: 1px solid {c('rule')}; }}
#Wordmark {{ {font_css('wordmark')} color: {c('ink')}; letter-spacing: 2.5px; }}
#WordmarkSub {{ {font_css('label')} color: {c('ink_faint')}; letter-spacing: 1.6px; }}
#NavButton {{
    text-align: left; padding: {s['snug']}px {s['base']}px;
    border: none; border-left: 2px solid transparent; border-radius: 0px;
    color: {c('ink_muted')}; {font_css('body')}
}}
#NavButton:hover {{ background: {c('surface_alt')}; color: {c('ink')}; }}
#NavButton:checked {{
    background: {c('surface')}; color: {c('ink')};
    border-left: 2px solid {c('shine')}; font-weight: 650;
}}
#NavButton:disabled {{ color: {c('ink_faint')}; }}
#NavGroup {{
    {font_css('label')} color: {c('ink_faint')}; letter-spacing: 1.4px;
    padding: {s['base']}px {s['base']}px {s['tight']}px {s['base']}px;
}}

/* --- surfaces ------------------------------------------------------------ */
#Card {{ background: {c('surface')}; border: 1px solid {c('rule')};
         border-radius: {RADIUS['card']}px; }}
#CardFlat {{ background: {c('surface_alt')}; border: 1px solid {c('rule')};
             border-radius: {RADIUS['card']}px; }}
#CardAccent {{ background: {c('brass_wash')}; border: 1px solid {c('brass_edge')};
               border-radius: {RADIUS['card']}px; }}
#Well {{ background: {c('sunken')}; border: 1px solid {c('rule')};
         border-radius: {RADIUS['small']}px; }}

#CardTitle {{ {font_css('card_title')} color: {c('ink')}; }}
#PageTitle {{ {font_css('page_title')} color: {c('ink')}; }}
#PageIntro {{ {font_css('subtitle')} color: {c('ink_muted')}; }}
#Display   {{ {font_css('display')} color: {c('ink')}; }}
#Figure    {{ {font_css('figure')} color: {c('ink')}; }}
#FigureSm  {{ {font_css('figure_sm')} color: {c('ink')}; }}
#Muted     {{ color: {c('ink_muted')}; }}
#Faint     {{ color: {c('ink_faint')}; {font_css('small')} }}
#Label     {{ {font_css('label')} color: {c('ink_faint')}; letter-spacing: 1.2px; }}
#Eyebrow   {{ {font_css('label')} color: {c('brass')}; letter-spacing: 1.6px; }}
#Mono      {{ {font_css('mono')} color: {c('ink')}; }}
#MonoFaint {{ {font_css('mono_small')} color: {c('ink_faint')}; }}
#Rule      {{ background: {c('rule')}; border: none; max-height: 1px; }}
#RuleShine {{ background: {c('shine')}; border: none; max-height: 1px; }}

/* --- buttons ------------------------------------------------------------- */
QPushButton {{
    background: {c('surface')}; color: {c('ink')};
    border: 1px solid {c('rule_strong')}; border-radius: {RADIUS['small']}px;
    padding: 6px {s['base']}px; {font_css('body')}
}}
QPushButton:hover {{ background: {c('surface_alt')}; border-color: {c('brass')}; }}
QPushButton:pressed {{ background: {c('select')}; }}
QPushButton:disabled {{ color: {c('ink_faint')}; border-color: {c('rule')};
                        background: {c('surface_alt')}; }}
QPushButton#Primary {{
    background: {c('brass')}; color: {c('ink_inverse')};
    border: 1px solid {c('brass')}; font-weight: 650;
}}
QPushButton#Primary:hover {{ background: {c('shine')}; border-color: {c('shine')};
                             color: {on_shine}; }}
QPushButton#Primary:disabled {{ background: {c('rule')}; border-color: {c('rule')};
                                color: {c('ink_faint')}; }}
QPushButton#Danger {{ color: {c('fault')}; border-color: {c('fault')}; }}
QPushButton#Danger:hover {{ background: {c('fault_wash')}; }}
QPushButton#Quiet {{
    background: transparent; border: 1px solid transparent;
    color: {c('ink_muted')}; padding: 3px {s['snug']}px;
}}
QPushButton#Quiet:hover {{ color: {c('ink')}; border-color: {c('rule')}; }}
QPushButton#Link {{
    background: transparent; border: none; color: {c('brass')};
    padding: 2px 0px; text-align: left; {font_css('small')}
}}
QPushButton#Link:hover {{ color: {c('shine')}; }}

/* --- inputs -------------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c('surface')}; color: {c('ink')};
    border: 1px solid {c('rule_strong')}; border-radius: {RADIUS['small']}px;
    padding: 5px {s['snug']}px;
    selection-background-color: {c('select')}; selection-color: {c('ink')};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {c('focus')}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled {{ background: {c('surface_alt')}; color: {c('ink_faint')}; }}
QLineEdit#Search {{ padding-left: {s['snug']}px; }}
QPlainTextEdit#MonoEdit, QTextEdit#MonoEdit {{ {font_css('editor')} }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none; width: 0px; height: 0px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {c('ink_muted')}; margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {c('surface')}; border: 1px solid {c('rule_strong')};
    selection-background-color: {c('select')}; selection-color: {c('ink')};
    outline: none; padding: 2px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px;
    background: {c('surface_alt')}; border-left: 1px solid {c('rule')}; }}

QCheckBox {{ spacing: {s['snug']}px; color: {c('ink')}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: {RADIUS['small']}px;
    border: 1px solid {c('rule_strong')}; background: {c('surface')};
}}
QCheckBox::indicator:hover {{ border-color: {c('brass')}; }}
QCheckBox::indicator:checked {{ background: {c('brass')}; border-color: {c('brass')}; }}
QCheckBox::indicator:disabled {{ background: {c('surface_alt')};
                                 border-color: {c('rule')}; }}

/* --- tabs, lists, tables ------------------------------------------------- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {c('ink_muted')};
    border: none; border-bottom: 2px solid transparent;
    padding: {s['snug']}px {s['base']}px; {font_css('body')}
}}
QTabBar::tab:selected {{ color: {c('ink')}; border-bottom: 2px solid {c('shine')};
                         font-weight: 650; }}
QTabBar::tab:hover {{ color: {c('ink')}; }}

QListWidget, QTreeWidget, QTableWidget {{
    background: {c('surface')}; border: 1px solid {c('rule')};
    border-radius: {RADIUS['small']}px; outline: none;
}}
QListWidget::item, QTreeWidget::item {{ padding: 4px {s['snug']}px;
                                        border: none; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {c('select')}; color: {c('ink')};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c('surface_alt')}; }}
QHeaderView::section {{
    background: {c('surface_alt')}; color: {c('ink_faint')};
    border: none; border-bottom: 1px solid {c('rule')};
    padding: {s['tight']}px {s['snug']}px; {font_css('label')}
    letter-spacing: 1.1px;
}}

/* --- scrollbars, splitters, misc ---------------------------------------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c('rule_strong')};
                               border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c('ink_faint')}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c('rule_strong')};
                                 border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {c('rule')}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QProgressBar {{
    background: {c('sunken')}; border: 1px solid {c('rule')};
    border-radius: {RADIUS['pill']}px; height: 6px; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c('brass')};
                       border-radius: {RADIUS['pill']}px; }}

QToolTip {{
    background: {c('ink')}; color: {c('ink_inverse')};
    border: none; padding: {s['tight']}px {s['snug']}px; {font_css('small')}
}}
QMenu {{ background: {c('surface')}; border: 1px solid {c('rule_strong')};
         padding: {s['tight']}px; }}
QMenu::item {{ padding: 5px {s['base']}px; }}
QMenu::item:selected {{ background: {c('select')}; }}
QMenu::separator {{ height: 1px; background: {c('rule')}; margin: 4px 0; }}
"""


# --- contrast ---------------------------------------------------------------
# Not ceremony. Checking these by eye passes pairings that fail.

def _srgb(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
