"""
Build the real interface, visit every page in both themes, save a screenshot.

This is the app's smoke test as much as its screenshot tool: it constructs
every page against the live Hermes install, lets each one's background refresh
finish, renders it, and fails loudly if any page raises. Runs headless, so it
works over SSH and in CI.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hermes_control import theme  # noqa: E402
from hermes_control.__main__ import PAGES, build  # noqa: E402

OUT = ROOT / "docs" / "screens"


def settle(app: QApplication, seconds: float, shell=None) -> None:
    """Pump the event loop until the page has actually finished loading.

    A fixed sleep was wrong in both directions: too long for a static page and
    too short for one that shells out twice, which is how the Connectors page
    was first captured mid-load showing "checking" and an empty list. Waiting
    on the job runner, then settling briefly for the repaint, tracks the real
    work instead of guessing at it.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 40)
        if shell is not None and not shell.jobs.busy:
            # Workers are done; let their results paint.
            quiet = time.monotonic() + 0.45
            while time.monotonic() < quiet:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
                time.sleep(0.02)
            return
        time.sleep(0.02)


#: Exceptions raised inside a Qt slot never reach the caller — Qt hands them
#: to sys.excepthook and keeps going, leaving a half-drawn page that renders
#: and saves perfectly well. Collecting them is the difference between "it
#: rendered" and "it worked".
QT_ERRORS: list[str] = []


def _collect(kind, value, tb) -> None:
    QT_ERRORS.append("".join(traceback.format_exception(kind, value, tb)))


def main() -> int:
    sys.excepthook = _collect
    OUT.mkdir(parents=True, exist_ok=True)
    app, shell = build([sys.argv[0]])
    shell.resize(1280, 860)
    shell.show()
    settle(app, 15.0, shell)

    failures: list[str] = []
    written: list[Path] = []

    for mode in (theme.LIGHT, theme.DARK):
        shell._choice = mode          # exercise the real path, not a shortcut
        shell.apply_appearance()
        settle(app, 10.0, shell)
        for page_class in PAGES:
            name = page_class.title
            try:
                shell.show_page(name)
                settle(app, 30.0, shell)
                target = OUT / f"{mode}-{name.lower()}.png"
                if not shell.grab().save(str(target)):
                    failures.append(f"{mode}/{name}: could not save image")
                else:
                    written.append(target)
                    print(f"  {mode:<5} {name:<10} -> {target.name} "
                          f"({target.stat().st_size // 1024} KB)")
            except Exception as exc:
                failures.append(f"{mode}/{name}: {type(exc).__name__}: {exc}")
                print(f"  {mode:<5} {name:<10} FAILED {exc}")

    print(f"\n{len(written)} screenshots written to {OUT}")
    if QT_ERRORS:
        print(f"\n{len(QT_ERRORS)} exception(s) escaped a Qt callback:")
        for error in QT_ERRORS[:5]:
            print("  " + error.strip().splitlines()[-1])
        failures.append(f"{len(QT_ERRORS)} exception(s) inside Qt callbacks")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("  -", failure)
        return 1
    print("every page rendered in both themes, with no exceptions "
          "raised anywhere including inside Qt callbacks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
