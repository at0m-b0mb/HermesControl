"""
Start the app.

Pages are registered here in rail order, which is also the only place that
knows the full set. Adding one is a single line.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import __version__, theme
from .cli import Hermes
from .ui.pages.colophon import ColophonPage
from .ui.pages.config import ConfigPage
from .ui.pages.console import ConsolePage
from .ui.pages.doctor import DoctorPage
from .ui.pages.gateway import GatewayPage
from .ui.pages.memory import MemoryPage
from .ui.pages.models import ModelsPage
from .ui.pages.runtime import RuntimePage
from .ui.pages.schedule import SchedulePage
from .ui.pages.skills import SkillsPage
from .ui.pages.soul import SoulPage
from .ui.shell import Shell

#: Rail order. Groups are drawn from each page's ``group``.
PAGES = (
    RuntimePage, ConsolePage, ModelsPage,       # Runtime
    SoulPage, SkillsPage, MemoryPage,           # Agent
    SchedulePage, GatewayPage,                  # Automation
    ConfigPage, DoctorPage, ColophonPage,       # Installation
)


def build(argv: list[str] | None = None) -> tuple[QApplication, Shell]:
    """Create the application and its window without showing anything.

    Split out from :func:`main` so a smoke test can build the whole interface,
    render it and quit without a human in front of it.
    """
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Hermes Control")
    app.setApplicationDisplayName("Hermes Control")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("at0m-b0mb")
    app.setFont(QFont(theme.sans(), 13))

    shell = Shell(Hermes())
    # Runtime first: its group heading has to be drawn before any page in it.
    for page_class in PAGES:
        shell.add_page(page_class(shell))
    shell.apply_appearance()
    shell.show_page(PAGES[0].title)
    return app, shell


def main(argv: list[str] | None = None) -> int:
    app, shell = build(argv)
    shell.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
