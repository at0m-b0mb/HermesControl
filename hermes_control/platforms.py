"""
Every operating-system difference in Hermes Control lives here.

The rest of the app asks this module where things are and what to run; it
never branches on ``sys.platform`` itself. That is the whole contract, and it
is what lets the same codebase drive Hermes on macOS, Windows and Linux.

Two facts shape the layout:

* Nous Hermes Agent keeps all of its state in one directory, chosen by the
  ``HERMES_HOME`` environment variable. Its own installer defaults that to
  ``~/.hermes`` on POSIX and ``%LOCALAPPDATA%\\hermes`` on Windows.
* That default is not always free. On this author's machine ``~/.hermes`` is
  already taken by an unrelated project of the same name, so Hermes Control
  installs into a *sibling* home and never writes to the default. Isolation is
  not a nicety here — picking the default would bury somebody's data.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IS_MAC = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = not IS_MAC and not IS_WINDOWS

#: Where we put Hermes. Deliberately *not* the upstream default — see module docstring.
ISOLATED_HOME_NAME = "hermes-agent"

INSTALL_SH_URL = "https://hermes-agent.nousresearch.com/install.sh"
INSTALL_PS1_URL = "https://hermes-agent.nousresearch.com/install.ps1"


# --- directories ------------------------------------------------------------

def home() -> Path:
    return Path.home()


def default_hermes_home() -> Path:
    """The HERMES_HOME *upstream* would choose. We avoid it; we report it."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(home() / "AppData" / "Local")
        return Path(base) / "hermes"
    return home() / ".hermes"


def isolated_hermes_home() -> Path:
    """The HERMES_HOME Hermes Control manages."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(home() / "AppData" / "Local")
        return Path(base) / ISOLATED_HOME_NAME
    return home() / f".{ISOLATED_HOME_NAME}"


def app_config_dir() -> Path:
    """Where *this* app keeps its own small amount of state."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(home() / "AppData" / "Roaming")
        return Path(base) / "HermesControl"
    if IS_MAC:
        return home() / "Library" / "Application Support" / "HermesControl"
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return Path(base) / "hermes-control"


def user_bin_dir() -> Path:
    """Where the upstream installer publishes its launcher on POSIX."""
    return home() / ".local" / "bin"


# --- the hermes executable --------------------------------------------------

def _exe(name: str) -> str:
    return f"{name}.exe" if IS_WINDOWS else name


@dataclass(frozen=True)
class Install:
    """A located Hermes installation."""

    hermes_home: Path
    install_dir: Path
    executable: Path

    @property
    def exists(self) -> bool:
        return self.executable.exists()


def install_dir_for(hermes_home: Path) -> Path:
    """The checkout directory the installer uses under a given home."""
    return hermes_home / "hermes-agent"


def executable_candidates(install_dir: Path) -> list[Path]:
    """Every place the real entry point might sit, best first.

    The installer builds a venv inside the checkout at ``.hermes`` and puts the
    console script in the usual place for the platform. A source checkout may
    also expose ``hermes_cli``; we prefer a real script because it has the
    venv's interpreter baked into its shebang.
    """
    venv = install_dir / ".hermes"
    bins = [venv / ("Scripts" if IS_WINDOWS else "bin")]
    # Some layouts nest the venv differently; look in the obvious siblings too.
    bins += [install_dir / ".venv" / ("Scripts" if IS_WINDOWS else "bin")]
    out: list[Path] = []
    for b in bins:
        out.append(b / _exe("hermes"))
    return out


def locate(hermes_home: Path | None = None) -> Install:
    """Find the managed Hermes install (whether or not it is there yet)."""
    hh = Path(hermes_home) if hermes_home else isolated_hermes_home()
    idir = install_dir_for(hh)
    for cand in executable_candidates(idir):
        if cand.exists():
            return Install(hh, idir, cand)
    # Not installed yet: report the path it *will* have, so callers can show it.
    return Install(hh, idir, executable_candidates(idir)[0])


def environment(hermes_home: Path) -> dict[str, str]:
    """The environment every Hermes subprocess must inherit.

    ``HERMES_HOME`` is the whole point: without it Hermes reads and writes the
    upstream default, which is exactly the directory we are staying out of.
    """
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    # Keep Hermes's own Python from importing the GUI's site-packages.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    # Stable, parseable output.
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# --- installation commands --------------------------------------------------

def install_command(hermes_home: Path, install_dir: Path,
                    script: Path, include_desktop: bool = False) -> list[str]:
    """Argv that runs an already-downloaded upstream installer, isolated.

    ``--non-interactive`` matters: the installer otherwise opens its own setup
    wizard on ``/dev/tty``, which a GUI has no way to answer.
    """
    if IS_WINDOWS:
        args = [
            powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script),
            "-NonInteractive",
            "-HermesHome", str(hermes_home),
            "--dir", str(install_dir),
        ]
        if include_desktop:
            args.append("-IncludeDesktop")
        return args
    args = [
        bash(), str(script),
        "--non-interactive",
        "--hermes-home", str(hermes_home),
        "--dir", str(install_dir),
    ]
    if include_desktop:
        args.append("--include-desktop")
    return args


def installer_url() -> str:
    return INSTALL_PS1_URL if IS_WINDOWS else INSTALL_SH_URL


def installer_filename() -> str:
    return "install.ps1" if IS_WINDOWS else "install.sh"


def bash() -> str:
    return shutil.which("bash") or "/bin/bash"


def powershell() -> str:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return "powershell"


# --- prerequisites ----------------------------------------------------------

@dataclass(frozen=True)
class Prereq:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _version_of(binary: str, *args: str) -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    try:
        out = subprocess.run([path, *args], capture_output=True, text=True,
                             timeout=12, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0] if text else path


def check_prerequisites() -> list[Prereq]:
    """What the upstream installer needs from the host.

    It ships its own pinned ``uv`` and fetches Node itself, so the host needs
    far less than you would guess: a shell, git, curl and a Python to
    bootstrap with.
    """
    checks: list[Prereq] = []

    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(Prereq("Python", sys.version_info >= (3, 10),
                         f"{py} at {sys.executable}"))

    git = _version_of("git", "--version")
    checks.append(Prereq("git", git is not None, git or "not found"))

    if IS_WINDOWS:
        ps = shutil.which("pwsh") or shutil.which("powershell")
        checks.append(Prereq("PowerShell", ps is not None, ps or "not found"))
    else:
        checks.append(Prereq("bash", Path(bash()).exists(), bash()))
        curl = _version_of("curl", "--version")
        checks.append(Prereq("curl", curl is not None, curl or "not found"))

    ollama = _version_of("ollama", "--version")
    checks.append(Prereq("Ollama", ollama is not None,
                         ollama or "not installed (only needed for local models)",
                         required=False))
    return checks


def disk_free_gb(path: Path) -> float:
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        return shutil.disk_usage(target).free / (1024 ** 3)
    except OSError:
        return -1.0


# --- opening things for the user --------------------------------------------

def reveal(path: Path) -> None:
    """Show a file or folder in the platform's file manager."""
    try:
        if IS_MAC:
            subprocess.Popen(["open", "-R" if path.is_file() else "", str(path)])
        elif IS_WINDOWS:
            subprocess.Popen(["explorer", f"/select,{path}" if path.is_file() else str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
    except OSError:
        pass


def terminal_hint(install: Install) -> str:
    """How the user would run this same Hermes from their own shell."""
    if IS_WINDOWS:
        return (f'$env:HERMES_HOME="{install.hermes_home}"; '
                f'& "{install.executable}"')
    return f'HERMES_HOME="{install.hermes_home}" "{install.executable}"'
