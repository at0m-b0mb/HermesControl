"""
One version, in four places.

The number appears in the package, the project metadata, the Colophon page and
the site's badge. Nothing keeps them in step, and a release where the About
screen disagrees with the tag is the kind of small wrongness that makes people
doubt the rest. This is cheap insurance.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_control import __version__  # noqa: E402


def test_version_is_sane() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_agrees() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in text, "pyproject.toml disagrees"


def test_colophon_agrees() -> None:
    text = (ROOT / "hermes_control" / "ui" / "pages" / "colophon.py").read_text(
        encoding="utf-8")
    assert f'VERSION = "{__version__}"' in text, "the Colophon page disagrees"


def test_site_badge_agrees() -> None:
    site = ROOT / "docs" / "index.html"
    if not site.exists():
        return
    text = site.read_text(encoding="utf-8")
    assert f"v{__version__}" in text, "the site's version badge disagrees"
