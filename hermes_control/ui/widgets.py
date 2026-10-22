"""
The pieces every page is built from.

Widgets ask :mod:`hermes_control.theme` for tokens and never name a colour
themselves, so re-theming is a single call and the contrast tests actually
cover what ships.

No emoji anywhere in here. Words carry the meaning; a glyph that renders as a
box on one platform and a colour emoji on another is not a design.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import theme


# --- small building blocks --------------------------------------------------

def label(text: str, role: str = "", *, wrap: bool = False,
          select: bool = False) -> QLabel:
    """A styled label. ``role`` is a QSS object name, not a colour."""
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    if select:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def rule(shine: bool = False) -> QFrame:
    line = QFrame()
    line.setObjectName("RuleShine" if shine else "Rule")
    line.setFixedHeight(1)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line


def spacer(height: int = 0) -> QWidget:
    widget = QWidget()
    if height:
        widget.setFixedHeight(height)
    else:
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


def button(text: str, kind: str = "", on_click: Callable[[], None] | None = None) -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        widget.clicked.connect(lambda: on_click())
    return widget


def row(*widgets: QWidget, spacing: int = 8, stretch_last: bool = False) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        if widget is None:
            continue
        layout.addWidget(widget, 1 if (stretch_last and index == len(widgets) - 1) else 0)
    return holder


def column(*widgets: QWidget, spacing: int = 8) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is not None:
            layout.addWidget(widget)
    return holder


class Card(QFrame):
    """A panel. ``flat`` for a nested well, ``accent`` to draw the eye once."""

    def __init__(self, title: str = "", *, flat: bool = False,
                 accent: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CardAccent" if accent else "CardFlat" if flat else "Card")
        self._layout = QVBoxLayout(self)
        pad = theme.SPACE["roomy"]
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(theme.SPACE["base"])
        if title:
            self._layout.addWidget(label(title, "CardTitle"))

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class PageHeader(QWidget):
    """Eyebrow, title, one line of intro, and an optional action strip."""

    def __init__(self, eyebrow: str, title: str, intro: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["tight"])
        layout.addWidget(label(eyebrow.upper(), "Eyebrow"))
        self._title_row = QHBoxLayout()
        self._title_row.setContentsMargins(0, 0, 0, 0)
        self._title_row.setSpacing(theme.SPACE["base"])
        self._title_row.addWidget(label(title, "PageTitle"))
        self._title_row.addStretch(1)
        layout.addLayout(self._title_row)
        if intro:
            layout.addWidget(label(intro, "PageIntro", wrap=True))

    def add_action(self, widget: QWidget) -> QWidget:
        self._title_row.addWidget(widget)
        return widget


class StatusDot(QWidget):
    """A filled circle plus a word. The word is what carries the meaning.

    Colour alone would fail anyone who cannot distinguish it, so the state is
    always spelled out beside the mark.
    """

    def __init__(self, state: str = "idle", text: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._state = state
        self._mode = theme.LIGHT
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["snug"])
        self._mark = _Dot(state)
        layout.addWidget(self._mark)
        self._label = label(text or state, "Muted")
        layout.addWidget(self._label)
        layout.addStretch(1)

    def set_state(self, state: str, text: str = "") -> None:
        self._state = state
        self._mark.set_state(state)
        self._label.setText(text or state)

    def apply_mode(self, mode: str) -> None:
        self._mode = mode
        self._mark.apply_mode(mode)


class _Dot(QWidget):
    def __init__(self, state: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._state = state
        self._mode = theme.LIGHT
        self.setFixedSize(10, 10)

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def apply_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        token = theme.state_token(self._state)
        painter.setBrush(QColor(theme.color(token, self._mode)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()


class Badge(QLabel):
    """A short, word-only tag: where a model runs, whether a key is set."""

    def __init__(self, text: str, token: str = "idle", parent: QWidget | None = None):
        super().__init__(text)
        self._token = token
        self._mode = theme.LIGHT
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apply_mode(theme.LIGHT)

    def set_token(self, token: str) -> None:
        self._token = token
        self.apply_mode(self._mode)

    def apply_mode(self, mode: str) -> None:
        self._mode = mode
        ink = theme.color(self._token, mode)
        wash = f"{self._token}_wash"
        ground = (theme.color(wash, mode) if wash in theme.PALETTE
                  else theme.color("surface_alt", mode))
        family, size, weight = theme.TYPE["label"]
        self.setStyleSheet(
            f"color: {ink}; background: {ground}; border: 1px solid {ink}33;"
            f"border-radius: {theme.RADIUS['pill']}px; padding: 2px 8px;"
            f"font-family: {family}; font-size: {size}px; font-weight: {weight};"
            f"letter-spacing: 1.1px;"
        )


class KeyValue(QWidget):
    """A definition list. Keys in small caps, values in mono where literal."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(theme.SPACE["snug"])
        self._rows: dict[str, QLabel] = {}

    def add(self, key: str, value: str, mono: bool = False) -> QLabel:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["base"])
        name = label(key.upper(), "Label")
        name.setFixedWidth(146)
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(name)
        value_label = label(value, "Mono" if mono else "", wrap=True, select=True)
        layout.addWidget(value_label, 1)
        self._layout.addWidget(holder)
        self._rows[key] = value_label
        return value_label

    def set(self, key: str, value: str) -> None:
        if key in self._rows:
            self._rows[key].setText(value)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()


def scroller(content: QWidget) -> QScrollArea:
    """Wrap a page body so a small window never clips it."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(content)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setFrameShape(QFrame.Shape.NoFrame)
    return area


# --- the signature element --------------------------------------------------

class ContextRibbon(QWidget):
    """How full the context window is, and where compaction will bite.

    This is the one widget here that no other tool could show, because it is
    made of Hermes's own mechanic. Hermes does not truncate a long
    conversation; at ``compression.threshold`` of the model's window it
    summarises the middle and keeps going, aiming to land at
    ``compression.target_ratio``. Those two numbers plus the live token count
    are the whole story of a session's health, and together they answer the
    question a chat UI usually leaves you guessing at: *is this conversation
    about to be rewritten?*

    So the ribbon draws the window as a bar, the live usage as a fill, and the
    threshold as a hard gold mark with the post-compaction target behind it.
    Every figure is real: the window from the provider, the tokens from the
    ``result`` event of the last turn.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = theme.LIGHT
        self._used = 0
        self._window = 0
        self._threshold = 0.5
        self._target = 0.2
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(420, 64)

    def set_budget(self, used: int, window: int,
                   threshold: float = 0.5, target: float = 0.2) -> None:
        self._used = max(0, int(used or 0))
        self._window = max(0, int(window or 0))
        self._threshold = min(max(float(threshold or 0.5), 0.05), 1.0)
        self._target = min(max(float(target or 0.2), 0.0), 1.0)
        self.update()

    def apply_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    @property
    def fraction(self) -> float:
        if not self._window:
            return 0.0
        return min(self._used / self._window, 1.0)

    def _fmt(self, n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mode = self._mode
        c = lambda n: QColor(theme.color(n, mode))  # noqa: E731

        pad = 2
        bar_h = 12
        width = max(self.width() - pad * 2, 10)
        top = 26

        # Caption line.
        painter.setFont(theme.font("label"))
        painter.setPen(QPen(c("ink_faint")))
        painter.drawText(pad, 12, "CONTEXT BUDGET")

        if not self._window:
            painter.setFont(theme.font("small"))
            painter.setPen(QPen(c("ink_faint")))
            painter.drawText(pad, top + bar_h + 16,
                             "No turn yet in this session.")
            painter.end()
            return

        # The trough: the whole window.
        trough = QPainterPath()
        trough.addRoundedRect(pad, top, width, bar_h, 6, 6)
        painter.fillPath(trough, c("sunken"))

        # The fill: what the conversation currently occupies. It turns from
        # calm to gold past the threshold, because past the threshold the next
        # turn triggers a rewrite.
        frac = self.fraction
        if frac > 0:
            fill_w = max(int(width * frac), 3)
            fill = QPainterPath()
            fill.addRoundedRect(pad, top, fill_w, bar_h, 6, 6)
            over = frac >= self._threshold
            painter.fillPath(fill, c("brass" if over else "live"))

        # Where compaction lands afterwards: target_ratio of the threshold.
        target_x = pad + int(width * self._threshold * self._target)
        painter.setPen(QPen(c("brass_edge"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(target_x, top - 3, target_x, top + bar_h + 3)

        # The threshold itself: a hard mark, no text on it.
        thr_x = pad + int(width * self._threshold)
        painter.setPen(QPen(c("shine"), 2))
        painter.drawLine(thr_x, top - 5, thr_x, top + bar_h + 5)

        # Outline last so the fill cannot bleed past it.
        painter.setPen(QPen(c("rule"), 1))
        painter.drawPath(trough)

        # Figures.
        painter.setFont(theme.font("mono_small"))
        painter.setPen(QPen(c("ink")))
        used_text = f"{self._fmt(self._used)} of {self._fmt(self._window)}"
        painter.drawText(pad, top + bar_h + 18, used_text)

        painter.setPen(QPen(c("ink_faint")))
        pct = f"{frac * 100:.0f}%"
        compact_at = f"compacts at {self._threshold * 100:.0f}%  to {self._target * 100:.0f}%"
        metrics = painter.fontMetrics()
        painter.drawText(self.width() - pad - metrics.horizontalAdvance(compact_at),
                         top + bar_h + 18, compact_at)
        painter.setPen(QPen(c("ink_muted")))
        painter.drawText(pad + metrics.horizontalAdvance(used_text) + 10,
                         top + bar_h + 18, pct)
        painter.end()
