"""
Platform branching, checked without the platforms.

These tests cannot prove Hermes Control runs on Windows — only a Windows
machine does that. What they can prove is the thing that was actually wrong
when this suite was written: that the *branches* produce the right paths and,
above all, the right installer flags. Those were guessed from documentation
and two of them were guessed wrong, which is a failure a simulated platform
catches and a code review did not.

The approach is to flip the module's platform flags and call the real
functions. Paths stay POSIX-shaped under the simulation, so what is asserted
is structure — which environment variable, which subdirectory, which argument
— not native path semantics.
"""

from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import platforms  # noqa: E402


def _become(monkeypatch, name: str):
    """Switch the module's platform flags inside a test body.

    Requesting two platform fixtures from one test does not work: they both
    patch the same three attributes, so the last one resolved wins silently
    and the test asserts against the wrong platform. Anything that needs to
    compare platforms switches explicitly with this instead.
    """
    monkeypatch.setattr(platforms, "IS_WINDOWS", name == "windows")
    monkeypatch.setattr(platforms, "IS_MAC", name == "mac")
    monkeypatch.setattr(platforms, "IS_LINUX", name == "linux")
    return platforms


@pytest.fixture()
def as_windows(monkeypatch):
    monkeypatch.setattr(platforms, "IS_WINDOWS", True)
    monkeypatch.setattr(platforms, "IS_MAC", False)
    monkeypatch.setattr(platforms, "IS_LINUX", False)
    monkeypatch.setenv("LOCALAPPDATA", "/fake/AppData/Local")
    monkeypatch.setenv("APPDATA", "/fake/AppData/Roaming")
    return platforms


@pytest.fixture()
def as_mac(monkeypatch):
    monkeypatch.setattr(platforms, "IS_WINDOWS", False)
    monkeypatch.setattr(platforms, "IS_MAC", True)
    monkeypatch.setattr(platforms, "IS_LINUX", False)
    return platforms


@pytest.fixture()
def as_linux(monkeypatch):
    monkeypatch.setattr(platforms, "IS_WINDOWS", False)
    monkeypatch.setattr(platforms, "IS_MAC", False)
    monkeypatch.setattr(platforms, "IS_LINUX", True)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return platforms


# --- homes ------------------------------------------------------------------

def test_windows_home_follows_localappdata(as_windows) -> None:
    assert str(as_windows.default_hermes_home()).endswith("Local/hermes")
    assert str(as_windows.isolated_hermes_home()).endswith("Local/hermes-agent")


def test_mac_home_is_a_dotfile(as_mac) -> None:
    assert as_mac.default_hermes_home().name == ".hermes"
    assert as_mac.isolated_hermes_home().name == ".hermes-agent"


def test_linux_home_is_a_dotfile(as_linux) -> None:
    assert as_linux.isolated_hermes_home().name == ".hermes-agent"


def test_the_managed_home_is_never_the_upstream_default(as_windows) -> None:
    """The entire isolation guarantee, in one assertion."""
    assert as_windows.isolated_hermes_home() != as_windows.default_hermes_home()


@pytest.mark.parametrize("fixture", ["as_mac", "as_linux", "as_windows"])
def test_isolation_holds_on_every_platform(fixture, request) -> None:
    mod = request.getfixturevalue(fixture)
    assert mod.isolated_hermes_home() != mod.default_hermes_home()


def test_windows_app_config_uses_roaming(as_windows) -> None:
    assert "Roaming" in str(as_windows.app_config_dir())


def test_mac_app_config_uses_application_support(as_mac) -> None:
    assert "Application Support" in str(as_mac.app_config_dir())


def test_linux_app_config_honours_xdg(as_linux, monkeypatch) -> None:
    assert str(as_linux.app_config_dir()).endswith(".config/hermes-control")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fake/xdg")
    assert str(as_linux.app_config_dir()) == "/fake/xdg/hermes-control"


# --- the launcher -----------------------------------------------------------

def test_windows_launcher_is_exe_or_cmd_in_dot_hermes_bin(as_windows) -> None:
    """Upstream publishes the checkout launcher to .hermes/bin on every OS.

    ``.hermes`` is a launcher directory, not a virtualenv, so there is no
    ``Scripts`` variant of it — an earlier version of this code looked in
    ``.hermes/Scripts`` and would have found nothing on Windows.
    """
    candidates = as_windows.executable_candidates(Path("/proj"))
    names = [c.name for c in candidates]
    assert "hermes.exe" in names
    assert "hermes.cmd" in names
    first = candidates[0]
    assert first.parent.as_posix().endswith(".hermes/bin"), first
    assert first.name == "hermes.exe"


def test_posix_launcher_is_dot_hermes_bin_hermes(as_mac) -> None:
    candidates = as_mac.executable_candidates(Path("/proj"))
    assert candidates[0] == Path("/proj/.hermes/bin/hermes")


@pytest.mark.parametrize("name", ["mac", "linux", "windows"])
def test_candidates_are_unique(monkeypatch, name) -> None:
    mod = _become(monkeypatch, name)
    candidates = mod.executable_candidates(Path("/proj"))
    assert len(candidates) == len(set(candidates))


def test_a_renamed_channel_build_is_still_found(as_mac, tmp_path) -> None:
    """A desktop channel build publishes `hermes-canary`, not `hermes`."""
    launchers = tmp_path / ".hermes" / "bin"
    launchers.mkdir(parents=True)
    (launchers / "hermes-acp").write_text("#!/bin/sh\n")   # a decoy
    canary = launchers / "hermes-canary"
    canary.write_text("#!/bin/sh\n")
    found = as_mac.find_executable(tmp_path)
    assert found == canary, "a channel build should still be located"


def test_acp_is_never_mistaken_for_the_cli(as_mac, tmp_path) -> None:
    launchers = tmp_path / ".hermes" / "bin"
    launchers.mkdir(parents=True)
    (launchers / "hermes-acp").write_text("#!/bin/sh\n")
    assert as_mac.find_executable(tmp_path) is None


# --- the installer ----------------------------------------------------------

def test_windows_installer_flags_are_the_powershell_ones(as_windows) -> None:
    """install.ps1 declares -HermesHome / -InstallDir / -NonInteractive.

    `--dir` is the *shell* installer's spelling and PowerShell does not bind
    it to -InstallDir at all, so passing it silently installed to the default
    location. This assertion is the one that would have caught it.
    """
    argv = as_windows.install_command(
        Path("/home"), Path("/home/hermes-agent"), Path("/tmp/install.ps1"))
    assert "-InstallDir" in argv, "PowerShell takes -InstallDir"
    assert "--dir" not in argv, "--dir is the shell installer's flag"
    assert "-HermesHome" in argv
    assert "-NonInteractive" in argv
    # Everything after -File is passed to the script rather than the host.
    assert argv.index("-File") < argv.index("-NonInteractive")
    assert argv[argv.index("-InstallDir") + 1] == "/home/hermes-agent"


def test_shell_installer_flags_are_the_posix_ones(as_mac) -> None:
    argv = as_mac.install_command(
        Path("/home"), Path("/home/hermes-agent"), Path("/tmp/install.sh"))
    assert "--non-interactive" in argv, "a GUI cannot answer the setup wizard"
    assert "--hermes-home" in argv
    assert "--dir" in argv
    assert "-InstallDir" not in argv
    assert argv[argv.index("--dir") + 1] == "/home/hermes-agent"


@pytest.mark.parametrize("name,flag", [("mac", "--include-desktop"),
                                       ("linux", "--include-desktop"),
                                       ("windows", "-IncludeDesktop")])
def test_desktop_build_is_opt_in(monkeypatch, name, flag) -> None:
    mod = _become(monkeypatch, name)
    plain = mod.install_command(Path("/h"), Path("/h/d"), Path("/t/i"))
    assert flag not in plain
    with_desktop = mod.install_command(
        Path("/h"), Path("/h/d"), Path("/t/i"), include_desktop=True)
    assert flag in with_desktop


@pytest.mark.parametrize("name,suffix", [("windows", ".ps1"), ("mac", ".sh"),
                                         ("linux", ".sh")])
def test_installer_url_matches_the_platform(monkeypatch, name, suffix) -> None:
    mod = _become(monkeypatch, name)
    assert mod.installer_url().endswith(suffix)
    assert mod.installer_filename().endswith(suffix)


# --- the environment every subprocess gets ---------------------------------

def test_environment_always_carries_hermes_home() -> None:
    env = platforms.environment(Path("/somewhere/else"))
    assert env["HERMES_HOME"] == "/somewhere/else"


def test_environment_does_not_leak_the_guis_interpreter(monkeypatch) -> None:
    """Hermes runs its own Python; our PYTHONPATH would poison its imports."""
    monkeypatch.setenv("PYTHONPATH", "/the/gui/site-packages")
    monkeypatch.setenv("PYTHONHOME", "/the/gui")
    env = platforms.environment(Path("/h"))
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_environment_forces_parseable_output() -> None:
    env = platforms.environment(Path("/h"))
    assert env["NO_COLOR"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


# --- the SQLite URI ---------------------------------------------------------

def test_a_windows_path_needs_as_uri_not_interpolation() -> None:
    """Documents why cli.sessions() builds its URI with Path.as_uri().

    A Windows path interpolated into a URI yields backslashes, which are
    escape characters to SQLite's URI parser, and a bare drive colon, which is
    not legal in a URI path.
    """
    win = PureWindowsPath(r"C:\Users\me\AppData\Local\hermes-agent\state.db")
    naive = f"file:{win}?mode=ro"
    assert "\\" in naive, "this is exactly what must not be handed to sqlite3"
    assert "file:C:" in naive
    posix = Path("/home/me/.hermes-agent/state.db")
    good = posix.as_uri() + "?mode=ro"
    assert good.startswith("file:///")
    assert "\\" not in good


def test_sessions_uses_as_uri() -> None:
    source = (Path(__file__).resolve().parents[1]
              / "hermes_control" / "cli.py").read_text(encoding="utf-8")
    assert "as_uri()" in source, "the read-only URI must be built with as_uri()"
    assert 'f"file:{db}' not in source, "interpolating a path breaks on Windows"
