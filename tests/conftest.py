"""
Make a Qt callback that raises fail the test that caused it.

This exists because of a bug that got through everything. A page referenced a
widget that was never created, so every refresh raised ``AttributeError`` — and
both the screenshot tool and the functional suite reported success, because an
exception inside a Qt slot does not propagate to the caller. Qt catches it,
hands it to ``sys.excepthook``, and carries on with a half-drawn page.

So the harness installs its own excepthook and fails the test if anything
landed in it. A test that renders a broken page now fails, which is the only
behaviour worth having.
"""

from __future__ import annotations

import os
import sys
import traceback

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Collector:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self._previous = None

    def install(self) -> None:
        self._previous = sys.excepthook
        sys.excepthook = self._hook

    def restore(self) -> None:
        if self._previous is not None:
            sys.excepthook = self._previous

    def _hook(self, kind, value, tb) -> None:
        self.errors.append("".join(traceback.format_exception(kind, value, tb)))


@pytest.fixture(autouse=True)
def qt_exceptions_are_failures():
    """Any exception escaping a Qt slot during a test fails that test."""
    collector = _Collector()
    collector.install()
    try:
        yield collector
    finally:
        collector.restore()
    if collector.errors:
        joined = "\n\n".join(collector.errors[:3])
        pytest.fail(
            f"{len(collector.errors)} exception(s) escaped a Qt callback "
            f"during this test:\n\n{joined}")
