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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hermes_control import theme  # noqa: E402
from hermes_control.__main__ import PAGES, build  # noqa: E402

OUT = ROOT / "docs" / "screens"


def settle(app: QApplication, seconds: float) -> None:
    """Pump the event loop so worker results actually land before we render."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 40)
        time.sleep(0.02)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app, shell = build([sys.argv[0]])
    shell.resize(1280, 860)
    shell.show()
    settle(app, 1.0)

    failures: list[str] = []
    written: list[Path] = []

    for mode in (theme.LIGHT, theme.DARK):
        shell._choice = mode          # exercise the real path, not a shortcut
        shell.apply_appearance()
        settle(app, 0.4)
        for page_class in PAGES:
            name = page_class.title
            try:
                shell.show_page(name)
                settle(app, 2.2)
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
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("  -", failure)
        return 1
    print("every page rendered in both themes with no exceptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
