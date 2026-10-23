"""
The driver: every conversation this app has with Hermes goes through here.

Hermes is a command-line program, and in the version this was written against
it is a *text* one — ``--json`` is rejected on ``status`` and ``cron``, and
``hermes tools`` refuses to run without a terminal at all. So the strategy is
deliberately mixed, and the choice per operation is about what stays true when
Hermes changes underneath us:

* **Writes go through the CLI.** ``hermes config set`` validates, migrates and
  decides whether a key belongs in ``config.yaml`` or ``.env``. Re-implementing
  that by editing YAML would mean re-implementing its judgement, badly.
* **Reads come from the files.** The config, the cron jobs, the skills and the
  session database are all on disk in stable formats. Reading them is faster
  than spawning a process, survives cosmetic changes to Hermes's output, and
  cannot be broken by a reflowed table.
* **Chat goes through ``--format stream-json``**, which is a documented, line
  oriented JSONL protocol and the one genuinely machine-readable surface.

Nothing here imports Qt. That keeps it testable without a display, and it is
why the UI layer runs these calls on worker threads rather than this module
knowing about threads at all.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import platforms

#: Hermes needs at least this much context window; a local server serving less
#: is refused outright by ``agent_init``. Discovered the hard way, and worth
#: surfacing in the UI because every Ollama default trips it.
MIN_CONTEXT_WINDOW = 64_000

_CREATE_NO_WINDOW = 0x08000000 if platforms.IS_WINDOWS else 0


@dataclass
class Result:
    """The outcome of one Hermes invocation."""

    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def message(self) -> str:
        """The most useful line to show a human when something went wrong."""
        if self.timed_out:
            return f"timed out after {self.duration:.0f}s"
        for stream in (self.stderr, self.stdout):
            for line in stream.splitlines():
                line = line.strip()
                if line and not line.startswith(("usage:", "Session:")):
                    return line
        return f"exit code {self.returncode}"


@dataclass
class Event:
    """One line of ``--format stream-json`` output."""

    type: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.raw.get("text", "") or ""

    @property
    def tool(self) -> str:
        return self.raw.get("name") or self.raw.get("tool") or ""

    @property
    def tokens(self) -> dict[str, int]:
        return self.raw.get("tokens") or {}

    @property
    def error(self) -> str:
        return self.raw.get("error") or ""

    @property
    def exit_code(self) -> int | None:
        return self.raw.get("exit_code")


class ChatStream:
    """A running ``hermes chat`` turn, consumed as it speaks.

    Kept as an object rather than a bare generator for one reason: a turn can
    run for minutes and the user is entitled to stop it. :meth:`cancel`
    terminates the process, which ends the iteration cleanly.
    """

    def __init__(self, argv: list[str], env: dict[str, str], cwd: Path | None = None):
        self.argv = argv
        self._proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            env=env, cwd=str(cwd) if cwd else None,
            creationflags=_CREATE_NO_WINDOW,
        )
        self._stderr: list[str] = []
        self._cancelled = False
        # Drain stderr concurrently: Hermes writes the session id and any
        # traceback there, and a full pipe would deadlock the stdout reader.
        self._drain = threading.Thread(target=self._read_stderr, daemon=True)
        self._drain.start()

    def _read_stderr(self) -> None:
        if self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def events(self) -> Iterator[Event]:
        """Yield each event as Hermes emits it."""
        if self._proc.stdout is not None:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    # Not every line is ours; a stray banner is not fatal.
                    continue
                if isinstance(payload, dict):
                    yield Event(type=str(payload.get("type", "unknown")), raw=payload)
        self._proc.wait()

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def returncode(self) -> int | None:
        return self._proc.poll()

    @property
    def stderr(self) -> str:
        return "\n".join(self._stderr)


@dataclass
class Status:
    """What ``hermes status`` says, parsed out of its box drawing."""

    model: str = ""
    provider: str = ""
    providers: str = ""
    gateway: str = ""
    platforms: str = ""
    jobs: int = 0
    raw: str = ""

    @property
    def gateway_running(self) -> bool:
        return "stopped" not in self.gateway.lower() and bool(self.gateway)


@dataclass
class Version:
    version: str = ""
    channel: str = ""
    commit: str = ""
    install_dir: str = ""
    python: str = ""
    raw: str = ""


class Hermes:
    """Everything the app can ask of one Hermes installation."""

    def __init__(self, install: platforms.Install | None = None):
        self.install = install or platforms.locate()

    # --- paths -------------------------------------------------------------

    @property
    def home(self) -> Path:
        return self.install.hermes_home

    @property
    def config_path(self) -> Path:
        return self.home / "config.yaml"

    @property
    def env_path(self) -> Path:
        return self.home / ".env"

    @property
    def soul_path(self) -> Path:
        return self.home / "SOUL.md"

    @property
    def memories_dir(self) -> Path:
        return self.home / "memories"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def installed(self) -> bool:
        return self.install.exists

    def env(self) -> dict[str, str]:
        return platforms.environment(self.home)

    # --- running -----------------------------------------------------------

    def run(self, args: list[str], timeout: float = 90.0,
            cwd: Path | None = None) -> Result:
        """Invoke Hermes once and wait for it."""
        argv = [str(self.install.executable), *args]
        start = time.monotonic()
        if not self.install.exists:
            return Result(argv, 127, "", "Hermes is not installed", 0.0)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                env=self.env(), stdin=subprocess.DEVNULL,
                cwd=str(cwd) if cwd else None,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            return Result(argv, 124, exc.stdout or "", exc.stderr or "",
                          time.monotonic() - start, timed_out=True)
        except OSError as exc:
            return Result(argv, 126, "", str(exc), time.monotonic() - start)
        return Result(argv, proc.returncode, proc.stdout or "", proc.stderr or "",
                      time.monotonic() - start)

    def popen(self, args: list[str]) -> subprocess.Popen:
        """Start a long-lived Hermes process (the gateway, the backend)."""
        return subprocess.Popen(
            [str(self.install.executable), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            env=self.env(), creationflags=_CREATE_NO_WINDOW,
        )

    # --- identity and health ----------------------------------------------

    def version(self) -> Version:
        result = self.run(["--version"], timeout=40)
        out = result.stdout
        info = Version(raw=out)
        if m := re.search(r"v([\d.]+)\s*\(([^)]*)\)", out):
            info.version = m.group(1)
        if m := re.search(r"·\s*(\w+)\s*·", out):
            info.channel = m.group(1)
        if m := re.search(r"local\s+([0-9a-f]{6,})", out):
            info.commit = m.group(1)
        if m := re.search(r"Install directory:\s*(.+)", out):
            info.install_dir = m.group(1).strip()
        if m := re.search(r"Python:\s*(.+)", out):
            info.python = m.group(1).strip()
        return info

    def status(self) -> Status:
        result = self.run(["status"], timeout=60)
        out = result.stdout
        status = Status(raw=out)
        fields = {
            "model": r"Model:\s*(.+)", "provider": r"Provider:\s*(.+)",
            "providers": r"Providers:\s*(.+)", "gateway": r"Gateway:\s*(.+)",
            "platforms": r"Platforms:\s*(.+)",
        }
        for name, pattern in fields.items():
            if m := re.search(pattern, out):
                setattr(status, name, m.group(1).strip())
        if m := re.search(r"Jobs:\s*(\d+)", out):
            status.jobs = int(m.group(1))
        return status

    def doctor(self, fix: bool = False) -> Result:
        return self.run(["doctor", *(["--fix"] if fix else [])], timeout=300)

    def config_check(self) -> Result:
        return self.run(["config", "check"], timeout=90)

    # --- configuration -----------------------------------------------------

    def read_config(self) -> dict[str, Any]:
        """The live ``config.yaml``, parsed. Empty mapping if unreadable."""
        try:
            text = self.config_path.read_text(encoding="utf-8", errors="replace")
            loaded = yaml.safe_load(text)
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, yaml.YAMLError):
            return {}

    def config_value(self, dotted: str) -> Any:
        """Look a dotted key up in the live config without spawning anything."""
        node: Any = self.read_config()
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    @staticmethod
    def format_value(value: Any) -> str:
        """Render a Python value the way ``config set`` wants to read it."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        return str(value)

    def config_set(self, dotted: str, value: Any, force: bool = False) -> Result:
        """Set one key, letting Hermes decide where it belongs and validate it."""
        args = ["config", "set", dotted, self.format_value(value)]
        if force:
            args.append("--force")
        return self.run(args, timeout=90)

    def config_unset(self, dotted: str) -> Result:
        return self.run(["config", "unset", dotted], timeout=90)

    def backup_config(self) -> Path | None:
        """Copy ``config.yaml`` aside before a batch of writes."""
        if not self.config_path.exists():
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.home / "backups" / f"config.yaml.{stamp}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.config_path.read_bytes())
            return target
        except OSError:
            return None

    # --- secrets -----------------------------------------------------------

    def read_env(self) -> dict[str, str]:
        """Parse ``.env``. Values are secrets: callers must not log them."""
        out: dict[str, str] = {}
        try:
            lines = self.env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return out
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[key.strip()] = value
        return out

    def set_secret(self, name: str, value: str) -> Result:
        """Write an UPPER_SNAKE key, which ``config set`` routes into ``.env``."""
        return self.run(["config", "set", name, value], timeout=90)

    def unset_secret(self, name: str) -> Result:
        return self.run(["config", "unset", name], timeout=90)

    # --- skills, jobs, sessions (read from disk) --------------------------

    def skills(self) -> list[dict[str, Any]]:
        """Installed skills, read from the skills directory.

        Each skill is a folder with a ``SKILL.md`` whose YAML front matter
        carries its name and description.
        """
        found: list[dict[str, Any]] = []
        if not self.skills_dir.is_dir():
            return found
        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            card = entry / "SKILL.md"
            meta: dict[str, Any] = {"name": entry.name, "path": str(entry),
                                    "description": "", "source": ""}
            if card.exists():
                try:
                    text = card.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if text.startswith("---"):
                    _, _, rest = text.partition("---")
                    front, _, _ = rest.partition("---")
                    try:
                        data = yaml.safe_load(front) or {}
                    except yaml.YAMLError:
                        data = {}
                    if isinstance(data, dict):
                        meta["description"] = str(data.get("description", ""))[:400]
                        meta["name"] = str(data.get("name", entry.name))
                meta["size"] = sum(
                    f.stat().st_size for f in entry.rglob("*") if f.is_file()
                )
            found.append(meta)
        return found

    def cron_jobs(self) -> list[dict[str, Any]]:
        """Scheduled jobs, read from ``cron/jobs.json``."""
        path = self.home / "cron" / "jobs.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            for key in ("jobs", "items", "entries"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [v | {"id": k} if isinstance(v, dict) else {"id": k}
                    for k, v in data.items()]
        return data if isinstance(data, list) else []

    def _state_db(self) -> Path | None:
        for name in ("state.db", "hermes.db", "sessions.db"):
            candidate = self.home / name
            if candidate.exists():
                return candidate
        for candidate in self.home.glob("*.db"):
            return candidate
        return None

    def sessions(self, limit: int = 200) -> list[dict[str, Any]]:
        """Recent sessions, read straight out of the SQLite state database.

        Opened read-only through a URI so a running gateway's WAL is never
        disturbed. The schema is Hermes's, so the column list is discovered
        rather than assumed.
        """
        db = self._state_db()
        if db is None:
            return []
        try:
            # Path.as_uri() is doing real work here, not tidiness: a Windows
            # path interpolated into a URI gives "file:C:\\Users\\..." , whose
            # backslashes are URI escapes and whose drive colon is not legal in
            # a URI path. as_uri() produces file:///C:/Users/... and
            # percent-encodes the rest.
            conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=4)
        except (sqlite3.Error, ValueError):
            return []
        try:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            table = next((t for t in ("sessions", "session", "conversations")
                          if t in tables), None)
            if table is None:
                return []
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            order = next((c for c in ("updated_at", "last_active", "created_at",
                                      "started_at", "rowid") if c in columns), "rowid")
            rows = conn.execute(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def log_text(self, name: str = "agent", lines: int = 200) -> str:
        """Tail a log. Read directly so a huge file never blocks the UI."""
        candidates = [self.logs_dir / f"{name}.log", self.logs_dir / name]
        for path in candidates:
            if not path.exists():
                continue
            try:
                with path.open("rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    size = handle.tell()
                    block = min(size, max(4096, lines * 400))
                    handle.seek(size - block)
                    data = handle.read().decode("utf-8", errors="replace")
                return "\n".join(data.splitlines()[-lines:])
            except OSError as exc:
                return f"(cannot read {path}: {exc})"
        return f"(no log named {name} in {self.logs_dir})"

    def log_names(self) -> list[str]:
        if not self.logs_dir.is_dir():
            return []
        return sorted(p.stem for p in self.logs_dir.glob("*.log"))

    # --- chat --------------------------------------------------------------

    def chat(self, prompt: str, *, model: str | None = None,
             provider: str | None = None, toolsets: str | None = None,
             skills: list[str] | None = None, resume: str | None = None,
             max_turns: int | None = None, yolo: bool = False,
             cwd: Path | None = None) -> ChatStream:
        """Start one turn, streaming.

        ``--oneshot`` is what makes this safe to drive from a GUI: without it
        Hermes stays interactive and waits on a terminal that does not exist.
        """
        args = ["chat", "-q", prompt, "--oneshot", "--format", "stream-json"]
        if model:
            args += ["-m", model]
        if provider:
            args += ["--provider", provider]
        if toolsets:
            args += ["-t", toolsets]
        for skill in skills or []:
            args += ["-s", skill]
        if resume:
            args += ["--resume", resume]
        if max_turns:
            args += ["--max-turns", str(max_turns)]
        if yolo:
            args.append("--yolo")
        argv = [str(self.install.executable), *args]
        return ChatStream(argv, self.env(), cwd)

    # --- gateway and backend ----------------------------------------------

    def gateway(self, action: str, timeout: float = 120.0) -> Result:
        """``status`` | ``start`` | ``stop`` | ``restart`` | ``install`` | ``uninstall``."""
        args = ["gateway", action]
        if action in ("stop", "restart"):
            args.append("--yes")
        return self.run(args, timeout=timeout)

    def gateway_running(self) -> bool:
        result = self.run(["gateway", "status"], timeout=45)
        text = (result.stdout + result.stderr).lower()
        if "not running" in text or "stopped" in text:
            return False
        return "running" in text

    def serve_status(self) -> Result:
        return self.run(["dashboard", "--status"], timeout=45)

    def serve_stop(self) -> Result:
        return self.run(["dashboard", "--stop"], timeout=60)
