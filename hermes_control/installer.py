"""
Installing Hermes Agent from inside the app.

This runs Nous's own installer rather than reimplementing it. That is the
whole design: the installer provisions a pinned ``uv``, fetches Node when a
build stage needs it, creates the virtualenv, syncs bundled skills and
migrates config — reproducing any of that here would mean maintaining a second
implementation that drifts.

Two flags make it usable from a window instead of a terminal. ``--non-interactive``
stops it opening a setup wizard on ``/dev/tty``, which a GUI cannot answer and
which otherwise hangs forever. And the isolation flags point it at a managed
home, so it never writes to the default location that may belong to something
else.

The script is downloaded to its own directory and run by absolute path. It is
third-party code either way, but keeping it out of the working directory means
an interpreter started there cannot pick up a neighbouring file by accident.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import platforms

#: Stages the installer announces, in order, so progress can be approximated
#: from its output without parsing anything brittle.
STAGES = (
    ("prerequisites", "Checking prerequisites"),
    ("repository", "Fetching the Hermes repository"),
    ("venv", "Creating the Python environment"),
    ("python-deps", "Installing dependencies"),
    ("products", "Building the command"),
    ("skills", "Syncing bundled skills"),
    ("complete", "Finishing up"),
)


@dataclass
class Line:
    """One line of installer output, lightly classified."""

    text: str
    stage: str = ""
    is_error: bool = False

    @property
    def clean(self) -> str:
        return self.text.rstrip()


class Installer:
    """Downloads and runs the upstream installer, streaming its output."""

    def __init__(self, hermes_home: Path | None = None,
                 install_dir: Path | None = None):
        self.hermes_home = Path(hermes_home or platforms.isolated_hermes_home())
        self.install_dir = Path(
            install_dir or platforms.install_dir_for(self.hermes_home))
        self._proc: subprocess.Popen | None = None
        self._cancelled = False

    # --- preflight ---------------------------------------------------------

    def preflight(self) -> list[str]:
        """Reasons not to start, in plain words. Empty means go."""
        problems: list[str] = []
        for prereq in platforms.check_prerequisites():
            if prereq.required and not prereq.ok:
                problems.append(f"{prereq.name} is required but was not found.")
        free = platforms.disk_free_gb(self.hermes_home)
        if 0 <= free < 5:
            problems.append(
                f"Only {free:.1f} GB free where Hermes would be installed; "
                f"it needs roughly 3 GB.")
        # Refusing to install over somebody else's directory is the point.
        upstream = platforms.default_hermes_home()
        if self.hermes_home == upstream and upstream.exists():
            problems.append(
                f"{upstream} already exists and is the upstream default. "
                f"Hermes Control will not install on top of it.")
        return problems

    @property
    def script_dir(self) -> Path:
        return platforms.app_config_dir() / "installer"

    def download(self) -> Path:
        """Fetch the installer for this platform into its own directory."""
        self.script_dir.mkdir(parents=True, exist_ok=True)
        target = self.script_dir / platforms.installer_filename()
        response = httpx.get(platforms.installer_url(), timeout=60,
                             follow_redirects=True)
        response.raise_for_status()
        if len(response.content) < 1000:
            raise RuntimeError(
                f"the installer at {platforms.installer_url()} came back "
                f"{len(response.content)} bytes; refusing to run it")
        target.write_bytes(response.content)
        if not platforms.IS_WINDOWS:
            target.chmod(0o700)
        return target

    # --- running -----------------------------------------------------------

    def run(self, include_desktop: bool = False) -> Iterator[Line]:
        """Download and run the installer, yielding each line it prints."""
        self._cancelled = False
        try:
            script = self.download()
        except Exception as exc:
            yield Line(f"Could not download the installer: {exc}", is_error=True)
            return
        yield Line(f"Installer downloaded to {script}")

        self.hermes_home.mkdir(parents=True, exist_ok=True)
        argv = platforms.install_command(
            self.hermes_home, self.install_dir, script, include_desktop)
        yield Line(f"Running: {' '.join(argv)}")

        env = dict(os.environ)
        env["HERMES_HOME"] = str(self.hermes_home)
        env["HERMES_INSTALL_DIR"] = str(self.install_dir)
        # The installer checks for a terminal before trying anything
        # interactive; make sure it does not find one.
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        env["CI"] = "1"

        try:
            self._proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, bufsize=1, env=env,
                cwd=str(self.script_dir),
                creationflags=0x08000000 if platforms.IS_WINDOWS else 0,
            )
        except OSError as exc:
            yield Line(f"Could not start the installer: {exc}", is_error=True)
            return

        stage = ""
        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            text = raw.rstrip("\n")
            lowered = text.lower()
            for key, _label in STAGES:
                if key.replace("-", " ") in lowered or key in lowered:
                    stage = key
                    break
            yield Line(text, stage=stage,
                       is_error=("error" in lowered or "failed" in lowered))
        code = self._proc.wait()
        self._proc = None

        if self._cancelled:
            yield Line("Installation cancelled.", is_error=True)
            return
        if code != 0:
            yield Line(f"The installer exited with code {code}.", is_error=True)
            return
        found = platforms.find_executable(self.install_dir)
        if found is None:
            yield Line(
                "The installer reported success but no hermes command was "
                f"found under {self.install_dir}.", is_error=True)
            return
        yield Line(f"Hermes Agent is installed at {found}", stage="complete")

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # --- removal -----------------------------------------------------------

    def uninstall(self) -> tuple[bool, str]:
        """Delete the managed home. Refuses to touch anything else."""
        home = self.hermes_home
        if home == platforms.default_hermes_home():
            return False, ("That is the upstream default home, which this app "
                           "does not manage. Refusing to delete it.")
        if not home.exists():
            return True, "Nothing to remove."
        try:
            shutil.rmtree(home)
        except OSError as exc:
            return False, f"Could not remove {home}: {exc}"
        return True, f"Removed {home}"
