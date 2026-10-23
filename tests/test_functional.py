"""
Drive the real interface against the real Hermes install.

The screenshot pass proves every page *renders*. It proves nothing about what
happens when a button is pressed, which is where the interesting bugs live, so
this suite clicks things: it edits a setting and applies it, checks the file
afterwards, puts it back, and reads the model verdicts against what Ollama
actually reports.

Everything here skips cleanly when there is no managed Hermes on the machine,
so it is safe to run anywhere.

The config test writes to the live config.yaml. It picks one inert key, asserts
the new value landed, and restores the original in a finally block — and Hermes
Control takes its own backup before any batch of writes regardless.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hermes_control import providers  # noqa: E402
from hermes_control.cli import Hermes  # noqa: E402

HERMES = Hermes()
needs_hermes = pytest.mark.skipif(
    not HERMES.installed, reason="no managed Hermes Agent on this machine")

#: Candidate keys to write during the round-trip test, most inert first. The
#: key has to be one that is actually *set* in this install — most of Hermes's
#: options ship commented out, so hardcoding one makes the test machine
#: specific. Picking it at run time is also a small test in its own right of
#: the config reader agreeing with the schema about what is set.
PROBE_CANDIDATES = (
    "updates.backup_keep",
    "memory.nudge_interval",
    "skills.creation_nudge_interval",
    "compression.max_attempts",
    "compression.protect_first_n",
)


def _probe_key() -> str:
    for key in PROBE_CANDIDATES:
        value = HERMES.config_value(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return key
    pytest.skip("no inert integer setting is set in this install")


PROBE_KEY = _probe_key() if HERMES.installed else PROBE_CANDIDATES[0]


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hermes_control.__main__ import build
    application, shell = build([sys.argv[0]])
    yield application, shell
    shell.jobs.wait_all(2000)
    QApplication.instance().processEvents()


def settle(application, seconds: float, until=None) -> None:
    """Pump the event loop until a condition holds or the time runs out."""
    from PySide6.QtCore import QEventLoop
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        if until is not None and until():
            return
        time.sleep(0.02)


# --- the driver -------------------------------------------------------------

@needs_hermes
def test_version_and_status_parse() -> None:
    """The text scrapers must actually find the fields they claim to."""
    version = HERMES.version()
    assert version.version, f"no version parsed from {version.raw!r}"
    assert version.install_dir, "install directory not parsed"
    status = HERMES.status()
    assert status.model, f"no model parsed from {status.raw!r}"
    assert status.gateway, "gateway state not parsed"


@needs_hermes
def test_config_round_trip() -> None:
    """A write through the CLI must be visible to the file reader."""
    original = HERMES.config_value(PROBE_KEY)
    assert isinstance(original, int), f"{PROBE_KEY} should be an int, got {original!r}"
    probe = original + 7
    try:
        result = HERMES.config_set(PROBE_KEY, probe)
        assert result.ok, f"config set failed: {result.message}"
        assert HERMES.config_value(PROBE_KEY) == probe, "write did not land"
    finally:
        HERMES.config_set(PROBE_KEY, original)
    assert HERMES.config_value(PROBE_KEY) == original, "restore failed"


@needs_hermes
def test_format_value_round_trips_through_hermes() -> None:
    """Booleans are the easy thing to get wrong: Python's True is not YAML's."""
    assert HERMES.format_value(True) == "true"
    assert HERMES.format_value(False) == "false"
    assert HERMES.format_value(None) == "null"
    assert HERMES.format_value(12) == "12"
    assert HERMES.format_value(["a", "b"]) == '["a", "b"]'


@needs_hermes
def test_reads_from_disk_do_not_lie() -> None:
    config = HERMES.read_config()
    assert config, "config.yaml read back empty"
    assert "model" in config
    assert isinstance(HERMES.skills(), list)
    assert isinstance(HERMES.cron_jobs(), list)
    assert isinstance(HERMES.sessions(), list)
    assert HERMES.log_names(), "no logs found"


# --- the interface ----------------------------------------------------------

@needs_hermes
def test_every_page_refreshes_without_raising(app) -> None:
    application, shell = app
    from hermes_control.__main__ import PAGES
    for page_class in PAGES:
        shell.show_page(page_class.title)
        settle(application, 2.5)


@needs_hermes
def test_config_page_applies_a_change(app) -> None:
    """The whole point of the Config page, exercised through the widgets."""
    application, shell = app
    page = shell.page("Config")
    shell.show_page("Config")
    settle(application, 4.0, until=lambda: page._schema is not None)
    assert page._schema is not None, "schema never loaded"

    original = HERMES.config_value(PROBE_KEY)
    assert isinstance(original, int)

    # Find the row through the UI the way a user would: search for it.
    page._search.setText(PROBE_KEY)
    settle(application, 1.5)
    row = next((r for r in page._rows if r.option.path == PROBE_KEY), None)
    assert row is not None, (
        f"{PROBE_KEY} not reachable by search; "
        f"got {[r.option.path for r in page._rows][:5]}")

    assert not row.changed, "a freshly loaded row must not look edited"
    assert not page._apply.isEnabled(), "Apply must be off with nothing pending"

    try:
        row._editor.setValue(original + 7)          # QSpinBox
        settle(application, 0.6)
        assert row.changed, "editing the widget did not mark the row changed"
        assert page._apply.isEnabled(), "Apply did not switch on"

        page._apply_changes()
        # Apply disables itself immediately so a second click cannot land, so
        # the button is useless as a completion signal. Wait on the only thing
        # that actually means the write happened: the file.
        settle(application, 60.0,
               until=lambda: HERMES.config_value(PROBE_KEY) == original + 7)
        assert HERMES.config_value(PROBE_KEY) == original + 7, (
            f"Apply did not reach config.yaml; page said: {page._message.text()!r}")
        settle(application, 3.0, until=lambda: not row.changed)
        assert not row.changed, "row still looks edited after a successful write"
    finally:
        HERMES.config_set(PROBE_KEY, original)
    assert HERMES.config_value(PROBE_KEY) == original


@needs_hermes
def test_models_page_verdicts_match_ollama(app) -> None:
    """The 64K verdict is the app's main claim; check it against the source."""
    application, shell = app
    page = shell.page("Models")
    shell.show_page("Models")
    settle(application, 15.0, until=lambda: bool(page._servers))
    assert page._servers, "no local servers probed"

    ollama = next((s for s in page._servers if s.name == "Ollama"), None)
    if ollama is None or not ollama.reachable:
        pytest.skip("Ollama is not running")

    assert ollama.models, "Ollama reachable but reported no models"
    for model in ollama.models:
        verdict = providers.context_verdict(model, 65_536)
        if model.context and model.context < providers.MIN_CONTEXT_WINDOW:
            assert not verdict.ok, f"{model.name} is under the floor but passed"
            assert verdict.state == "error"
            assert not verdict.fix, "no setting can rescue an undertrained window"
        elif model.context:
            assert verdict.ok, f"{model.name} clears the floor but was refused"


@needs_hermes
def test_a_model_under_the_floor_cannot_be_selected(app) -> None:
    """A disabled button is the point: it stops a doomed turn being started."""
    application, shell = app
    page = shell.page("Models")
    shell.show_page("Models")
    settle(application, 15.0, until=lambda: bool(page._servers))
    small = [m for s in page._servers for m in s.models
             if m.context and m.context < providers.MIN_CONTEXT_WINDOW]
    if not small:
        pytest.skip("no undersized local model to check against")
    verdict = providers.context_verdict(small[0], 999_999)
    assert not verdict.ok
    assert "cannot be stretched" in verdict.detail


@needs_hermes
@pytest.mark.skipif(os.environ.get("HC_SKIP_SLOW") == "1",
                    reason="HC_SKIP_SLOW=1")
def test_console_runs_a_real_turn(app) -> None:
    """End to end through the widgets: type, send, receive, account."""
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 3.0)

    page._input.setPlainText("Reply with exactly one word: PONG")
    page.send()
    assert page._stream is not None, "send did not start a turn"
    assert not page._send.isEnabled(), "Send must be disabled mid-turn"

    settle(application, 420.0, until=lambda: page._stream is None)
    assert page._stream is None, "the turn never finished"
    assert page._send.isEnabled(), "Send was not re-enabled"

    transcript = page._transcript.toPlainText()
    assert "PONG" in transcript.upper(), f"no answer in transcript: {transcript[-300:]!r}"
    assert page.ribbon._used > 0, "the ribbon never received a token count"
    assert page.ribbon._window > 0, "the ribbon has no window to measure against"
    assert 0 < page.ribbon.fraction <= 1.0


@needs_hermes
def test_theme_switch_reaches_painted_widgets(app) -> None:
    """QSS restyles most things; painted widgets only change if told."""
    from hermes_control import theme
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 1.0)
    for mode in (theme.LIGHT, theme.DARK):
        shell._choice = mode
        shell.apply_appearance()
        settle(application, 0.5)
        assert shell.mode == mode
        assert page.ribbon._mode == mode, (
            "the context ribbon paints itself and did not get the new mode")

# --- the state a new user actually sees -------------------------------------

@pytest.fixture()
def fresh(app, tmp_path):
    """Point the whole app at an empty HERMES_HOME, then put it back.

    The new-user state had never once been looked at: every check so far ran
    against a working install, which is the one configuration guaranteed not
    to expose a first-run bug.
    """
    from hermes_control import platforms
    from hermes_control.cli import Hermes
    application, shell = app
    original = shell.hermes
    empty = Hermes(platforms.locate(tmp_path / "empty"))
    shell.hermes = empty
    for page in shell._pages.values():
        page.hermes = empty
    yield application, shell, empty
    shell.hermes = original
    for page in shell._pages.values():
        page.hermes = original
    shell.show_page("Runtime")
    settle(application, 2.0)


def test_nothing_installed_renders_every_page(fresh) -> None:
    from hermes_control.__main__ import PAGES
    application, shell, empty = fresh
    assert not empty.installed
    for page_class in PAGES:
        shell.show_page(page_class.title)
        settle(application, 1.2)


def test_console_refuses_to_send_with_nothing_installed(fresh) -> None:
    """Offering Send here produces a stack trace instead of an answer."""
    application, shell, _empty = fresh
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 3.0, until=lambda: not page._send.isEnabled())
    assert not page._send.isEnabled(), "Send must be off with no Hermes"
    assert not page._input.isEnabled()
    assert "not installed" in page._state.text().lower()

    # Even called directly it must do nothing.
    page._input.setPlainText("hello")
    page.send()
    assert page._stream is None, "send() started a turn it could not finish"


def test_console_does_not_claim_hosted_when_nothing_is_set(fresh) -> None:
    application, shell, _empty = fresh
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 3.0)
    label = page._model_label.text().lower()
    assert "hosted" not in label, (
        f"an unconfigured provider was described as hosted: {label!r}")


def test_setup_installs_where_the_app_is_looking(fresh) -> None:
    application, shell, empty = fresh
    page = shell.page("Setup")
    shell.show_page("Setup")
    settle(application, 3.0)
    assert page._installer.hermes_home == empty.home, (
        "Setup would install somewhere the rest of the app does not read")

# --- session continuity -----------------------------------------------------

@needs_hermes
@pytest.mark.skipif(os.environ.get("HC_SKIP_SLOW") == "1", reason="HC_SKIP_SLOW=1")
def test_a_second_turn_continues_the_same_conversation() -> None:
    """--resume has to be passed a real id, and the id is not where it looks.

    The `system` event declares a `session_id` and leaves it empty; the real
    one arrives on the closing `result` event. Reading only the former meant
    every turn silently began a new conversation, which no amount of looking
    at the transcript would reveal.

    Asserted mechanically rather than by asking the model what it remembers:
    the session must be reused, no new session may appear, and the input
    token count must grow because the earlier turn is now part of the prompt.
    """
    def session_ids() -> set:
        return {s.get("session_id") or s.get("id")
                for s in HERMES.sessions(limit=500)}

    before = session_ids()
    first = HERMES.chat("Say OK.", max_turns=2)
    first_result = next(e for e in first.events() if e.type == "result")
    session = first_result.raw.get("session_id")
    assert session, "the result event must carry the session id"
    after_first = session_ids()
    assert len(after_first - before) == 1, "the first turn should open a session"

    second = HERMES.chat("Say OK again.", resume=session, max_turns=2)
    second_result = next(e for e in second.events() if e.type == "result")
    assert second_result.raw.get("session_id") == session, (
        "the resumed turn landed in a different session")
    assert session_ids() == after_first, "resuming must not open a new session"
    assert (second_result.tokens.get("input", 0)
            > first_result.tokens.get("input", 0)), (
        "input did not grow, so the earlier turn was not in the prompt")


@needs_hermes
def test_the_console_reads_the_session_id_from_the_result_event(app) -> None:
    """A unit-ish check so the slow test above is not the only guard."""
    from hermes_control.cli import Event
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 2.0)
    page._session = ""
    page._on_event(Event("system", {"session_id": "", "model": "x"}))
    assert page._session == "", "the system event's id is empty by design"
    page._on_event(Event("result", {"session_id": "local-abc123",
                                    "tokens": {}, "exit_code": 0}))
    assert page._session == "local-abc123", (
        "the result event's session id was ignored, so --resume would never "
        "be passed")
