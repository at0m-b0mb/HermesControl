"""
Colophon — what this is built from, and the decisions worth stating.

A colophon is the one page allowed to talk about itself. It names the
typefaces, explains the palette, and records the two choices a user of this
app deserves to have in writing: that it never touches the upstream default
HERMES_HOME, and that it does not own the agent it drives.
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ... import platforms, theme
from .. import widgets as w
from ..shell import Page

VERSION = "1.3.0"


class ColophonPage(Page):
    title = "Colophon"
    group = "Installation"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(18)

        layout.addWidget(w.PageHeader(
            "Installation", "Colophon",
            f"Hermes Control {VERSION} — a control panel for Nous Research's "
            f"Hermes Agent."))

        scope = w.Card("What this is")
        scope.add(w.label(
            "Hermes Agent is Nous Research's work, MIT licensed, and it does "
            "the thinking. This app installs it, keeps it isolated, exposes "
            "every setting it documents, and gives it a window. It is not a "
            "fork and it adds no model of its own.", "", wrap=True))
        scope.add(w.label(
            "The settings editor has no list of settings in it. It reads the "
            "annotated config.yaml that your install shipped with, so it "
            "describes your version of Hermes rather than the one this was "
            "written against — including options added later.", "Faint", wrap=True))
        layout.addWidget(scope)

        isolation = w.Card("Isolation", accent=True)
        self._isolation = w.KeyValue()
        isolation.add(self._isolation)
        isolation.add(w.label(
            "Hermes stores everything under one directory named by HERMES_HOME, "
            "and its installer defaults to a path that may already be taken. "
            "This app always uses a sibling and passes HERMES_HOME explicitly "
            "on every command, so another Hermes on the same machine is never "
            "read or written.", "Faint", wrap=True))
        layout.addWidget(isolation)

        design = w.Card("Design")
        self._fonts = w.KeyValue()
        design.add(self._fonts)
        design.add(w.label(
            "Warm paper and ink with a single accent. There are two golds, not "
            "one: a deep brass legible as small text, and a bright shine used "
            "only on marks that carry no words. Dark mode is true black with "
            "neutral greys above it. Every colour is declared as a light/dark "
            "pair at the point of definition, and a test suite checks every "
            "text pairing against WCAG AA in both themes — it caught a washed "
            "out grey the eye had passed.", "Faint", wrap=True))
        layout.addWidget(design)

        ribbon = w.Card("The ribbon")
        ribbon.add(w.label(
            "The meter on the Console is the one thing here no other tool "
            "could show, because it is made of Hermes's own mechanic. Hermes "
            "does not truncate a long conversation: past a threshold it "
            "rewrites the middle into a summary and continues. The ribbon "
            "draws the window, the live token count, the threshold where that "
            "happens and the target it compacts down to — so you can see a "
            "rewrite coming instead of discovering it afterwards.",
            "Faint", wrap=True))
        layout.addWidget(ribbon)

        build = w.Card("Build")
        self._build = w.KeyValue()
        build.add(self._build)
        layout.addWidget(build)

        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    def refresh(self) -> None:
        import platform
        import sys

        self._isolation.clear()
        self._isolation.add("Managed home", str(self.hermes.home), mono=True)
        self._isolation.add("Upstream default",
                            str(platforms.default_hermes_home()), mono=True)
        self._fonts.clear()
        self._fonts.add("Display", f"{theme.serif()} — identity, titles and figures")
        self._fonts.add("Interface", f"{theme.sans()} — anything you operate")
        self._fonts.add("Literal", f"{theme.mono()} — config keys, model names, output")
        self._build.clear()
        self._build.add("Hermes Control", VERSION)
        self._build.add("Python", sys.version.split()[0], mono=True)
        try:
            from PySide6 import QtCore
            self._build.add("Qt", f"PySide6 on Qt {QtCore.qVersion()}", mono=True)
        except Exception:
            pass
        self._build.add("Host", f"{platform.system()} {platform.release()}", mono=True)
