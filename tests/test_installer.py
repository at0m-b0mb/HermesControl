"""
Tests for the installer — mostly its refusals.

An installer's dangerous behaviour is writing somewhere it should not, and the
one guarantee this whole app rests on is that it never touches the upstream
default HERMES_HOME. That guarantee is worth more than a comment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import platforms  # noqa: E402
from hermes_control.installer import STAGES, Installer  # noqa: E402


def test_defaults_to_the_managed_home_not_the_upstream_one() -> None:
    installer = Installer()
    assert installer.hermes_home == platforms.isolated_hermes_home()
    assert installer.hermes_home != platforms.default_hermes_home()


def test_install_dir_lives_under_the_managed_home() -> None:
    installer = Installer()
    assert installer.install_dir.parent == installer.hermes_home


def test_it_refuses_to_install_over_the_upstream_default() -> None:
    upstream = platforms.default_hermes_home()
    if not upstream.exists():
        pytest.skip("the upstream default does not exist on this machine")
    problems = Installer(hermes_home=upstream).preflight()
    assert any("upstream default" in p for p in problems), problems


def test_it_refuses_to_delete_the_upstream_default() -> None:
    """The destructive path gets its own assertion. This one matters most."""
    installer = Installer(hermes_home=platforms.default_hermes_home())
    ok, message = installer.uninstall()
    assert ok is False
    assert "refusing" in message.lower()


def test_uninstall_of_a_missing_managed_home_is_a_no_op(tmp_path) -> None:
    installer = Installer(hermes_home=tmp_path / "not-there")
    ok, message = installer.uninstall()
    assert ok is True
    assert "nothing" in message.lower()


def test_uninstall_removes_only_the_managed_home(tmp_path) -> None:
    managed = tmp_path / "managed"
    (managed / "inside").mkdir(parents=True)
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    (neighbour / "keep.txt").write_text("untouched")
    ok, _ = Installer(hermes_home=managed).uninstall()
    assert ok
    assert not managed.exists()
    assert (neighbour / "keep.txt").read_text() == "untouched"


def test_preflight_reports_a_full_disk(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(platforms, "disk_free_gb", lambda _p: 0.4)
    problems = Installer(hermes_home=tmp_path / "managed").preflight()
    assert any("free" in p for p in problems), problems


def test_stages_are_ordered_and_labelled() -> None:
    keys = [k for k, _ in STAGES]
    assert keys[0] == "prerequisites"
    assert keys[-1] == "complete"
    assert len(keys) == len(set(keys))
    for _key, label in STAGES:
        assert label and label[0].isupper()


def test_the_script_is_downloaded_outside_the_working_directory() -> None:
    """Third-party code is kept away from anything it could shadow."""
    installer = Installer()
    assert installer.script_dir.is_absolute()
    assert installer.script_dir.parent == platforms.app_config_dir()
    assert Path.cwd() not in installer.script_dir.parents
