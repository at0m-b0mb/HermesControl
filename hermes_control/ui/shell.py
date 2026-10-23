"""
The window: a rail on the left, one page at a time on the right.

Pages are registered, not hard-wired, so each one is a self-contained class
that knows nothing about its neighbours. The rail is grouped using Hermes's
own vocabulary — Runtime, Console, Soul, Cron, Gateway — rather than the
Dashboard/Settings/Advanced triplet every generated interface reaches for.
"""

from __future__ import annotations


from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import theme
from ..cli import Hermes
from . import widgets as w
from .tasks import JobRunner

APP_NAME = "Hermes Control"
APP_TAGLINE = "AGENT CONTROL"


class Page(QWidget):
    """Base class for a rail destination.

    ``refresh`` is called whenever the page becomes visible, so a page never
    has to poll. ``apply_mode`` is only for widgets that paint themselves;
    everything else is restyled by the application stylesheet.
    """

    #: Shown in the rail.
    title = "Page"
    #: Rail group heading.
    group = ""
    #: Small word above the page title.
    eyebrow = ""

    def __init__(self, app: Shell, parent: QWidget | None = None):
        super().__init__(parent)
        self.app = app
        self.hermes: Hermes = app.hermes
        self.jobs: JobRunner = app.jobs

    def refresh(self) -> None:
        """Re-read whatever this page shows. Safe to call repeatedly."""

    def apply_mode(self, mode: str) -> None:
        """Hand the current light/dark mode to self-painting children."""
        for child in self.findChildren(QWidget):
            handler = getattr(child, "apply_mode", None)
            if callable(handler) and child is not self:
                handler(mode)


class Shell(QMainWindow):
    """The application window."""

    mode_changed = Signal(str)

    def __init__(self, hermes: Hermes | None = None):
        super().__init__()
        self.hermes = hermes or Hermes()
        self.jobs = JobRunner(self)
        self.settings = QSettings("at0m-b0mb", "HermesControl")
        self._choice = str(self.settings.value("appearance", theme.AUTO))
        self._mode = theme.resolve(self._choice)
        self._pages: dict[str, Page] = {}
        self._buttons: dict[str, QPushButton] = {}

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 800)
        self.setMinimumSize(940, 620)

        host = QWidget()
        host.setObjectName("PageHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._rail = self._build_rail()
        layout.addWidget(self._rail)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(host)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.refresh_current)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.cycle_appearance)

        # Re-resolve AUTO periodically so following the OS actually follows it.
        self._watch = QTimer(self)
        self._watch.setInterval(4000)
        self._watch.timeout.connect(self._recheck_auto)
        self._watch.start()

    # --- rail --------------------------------------------------------------

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(206)
        layout = QVBoxLayout(rail)
        pad = theme.SPACE["base"]
        layout.setContentsMargins(0, theme.SPACE["wide"], 0, theme.SPACE["base"])
        layout.setSpacing(0)

        mark = QWidget()
        mark_layout = QVBoxLayout(mark)
        mark_layout.setContentsMargins(pad, 0, pad, 0)
        mark_layout.setSpacing(2)
        mark_layout.addWidget(w.label(APP_NAME.split()[0].upper(), "Wordmark"))
        mark_layout.addWidget(w.label(APP_TAGLINE, "WordmarkSub"))
        layout.addWidget(mark)
        layout.addSpacing(theme.SPACE["snug"])
        shine = w.rule(shine=True)
        shine.setFixedWidth(34)
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(pad, 0, pad, 0)
        holder_layout.addWidget(shine)
        holder_layout.addStretch(1)
        layout.addWidget(holder)
        layout.addSpacing(theme.SPACE["roomy"])

        self._rail_body = QVBoxLayout()
        self._rail_body.setContentsMargins(0, 0, 0, 0)
        self._rail_body.setSpacing(0)
        layout.addLayout(self._rail_body)
        layout.addStretch(1)

        self._appearance_button = w.button("Appearance: auto", "Quiet",
                                           self.cycle_appearance)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(pad, 0, pad, 0)
        footer_layout.setSpacing(theme.SPACE["tight"])
        footer_layout.addWidget(w.rule())
        footer_layout.addSpacing(theme.SPACE["tight"])
        footer_layout.addWidget(self._appearance_button)
        layout.addWidget(footer)
        return rail

    # --- pages -------------------------------------------------------------

    def add_page(self, page: Page) -> None:
        key = page.title
        if page.group and page.group not in self._seen_groups():
            self._rail_body.addWidget(w.label(page.group.upper(), "NavGroup"))
        nav = QPushButton(page.title)
        nav.setObjectName("NavButton")
        nav.setCheckable(True)
        nav.setCursor(Qt.CursorShape.PointingHandCursor)
        nav.clicked.connect(lambda _=False, k=key: self.show_page(k))
        self._rail_body.addWidget(nav)
        self._nav_group.addButton(nav)
        self._buttons[key] = nav
        self._pages[key] = page
        self._stack.addWidget(page)

    def _seen_groups(self) -> set[str]:
        return {p.group for p in self._pages.values() if p.group}

    def show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        for name, nav in self._buttons.items():
            nav.setChecked(name == key)
        page.apply_mode(self._mode)
        page.refresh()

    def current_page(self) -> Page | None:
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, Page) else None

    def refresh_current(self) -> None:
        page = self.current_page()
        if page is not None:
            page.refresh()

    def refresh_all(self) -> None:
        for page in self._pages.values():
            page.refresh()

    def page(self, key: str) -> Page | None:
        return self._pages.get(key)

    # --- appearance --------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    def cycle_appearance(self) -> None:
        order = [theme.AUTO, theme.LIGHT, theme.DARK]
        self._choice = order[(order.index(self._choice) + 1) % len(order)
                             ] if self._choice in order else theme.AUTO
        self.settings.setValue("appearance", self._choice)
        self.apply_appearance()

    def _recheck_auto(self) -> None:
        if self._choice == theme.AUTO and theme.resolve(theme.AUTO) != self._mode:
            self.apply_appearance()

    def apply_appearance(self) -> None:
        """Resolve the stored choice and restyle everything."""
        self._mode = theme.resolve(self._choice)
        self.setStyleSheet(theme.stylesheet(self._mode))
        self._appearance_button.setText(f"Appearance: {self._choice}")
        for page in self._pages.values():
            page.apply_mode(self._mode)
        self.mode_changed.emit(self._mode)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.jobs.wait_all(1500)
        super().closeEvent(event)
