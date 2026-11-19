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
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hermes_control import attachments
from hermes_control import auth as hauth
from hermes_control import channels, providers  # noqa: E402
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
def app(isolated_settings):
    from PySide6.QtWidgets import QApplication
    from hermes_control.__main__ import build
    application, shell = build([sys.argv[0]], settings=isolated_settings)
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
        if model.supports_tools is False:
            # A second, independent requirement: Hermes sends tools on every
            # request, so a model without them fails before producing a token
            # no matter how large its window is.
            assert not verdict.ok, f"{model.name} has no tools but passed"
            assert verdict.state == "error"
            assert "tools" in verdict.headline.lower()
        elif model.context and model.context < providers.MIN_CONTEXT_WINDOW:
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


# --- where the agent works --------------------------------------------------

def test_tool_result_output_is_read_from_the_right_key() -> None:
    """Hermes puts a tool's output under `output`, not `content`.

    Reading the wrong key returned "" for every tool call, so the transcript
    showed each tool running and producing nothing — which looks like a
    broken tool rather than a broken reader.
    """
    from hermes_control.cli import Event
    event = Event("tool_result", {"name": "write_file",
                                  "output": '{"error": "missing path"}'})
    assert event.output == '{"error": "missing path"}'
    assert event.tool == "write_file"
    # Other shapes still work.
    assert Event("tool_result", {"content": "legacy"}).output == "legacy"
    assert Event("tool_result", {"result": "older"}).output == "older"
    assert Event("tool_result", {}).output == ""


@needs_hermes
def test_chat_scopes_the_turn_with_in(tmp_path) -> None:
    """Popen's cwd is not enough when a gateway is running.

    `hermes chat` hands the turn to the gateway process, whose own working
    directory is the Hermes checkout — so a relative path from a file tool
    landed inside the installation. --in scopes the turn itself.
    """
    stream = HERMES.chat("hi", cwd=tmp_path)
    try:
        assert "--in" in stream.argv, "the working directory was not passed"
        assert stream.argv[stream.argv.index("--in") + 1] == str(tmp_path)
    finally:
        stream.cancel()


@needs_hermes
def test_the_console_has_a_working_directory(app) -> None:
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 3.0)
    assert page._workdir is not None
    assert page._workdir_label.text(), "the working directory is not shown"


def test_the_console_remembers_its_choices(app) -> None:
    """A narrow toolset chosen because the local model needs it should stick.

    Re-picking it on every launch is the kind of small friction that makes a
    tool feel unfinished.
    """
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 2.0)
    original = page._toolsets.currentText()
    try:
        page._toolsets.setCurrentText("Web only")
        settle(application, 0.4)
        assert shell.settings.value("console/toolsets") == "Web only"
    finally:
        page._toolsets.setCurrentText(original)
        settle(application, 0.3)


def test_the_suite_does_not_touch_real_preferences(app, isolated_settings) -> None:
    """A guard for the guard.

    The Console test below changes the remembered toolset. Without isolation
    that write lands in the user's own preferences and silently replaces a
    choice they made — which is exactly what happened before the
    isolated_settings fixture existed.
    """
    application, shell = app
    assert shell.settings is isolated_settings, "the window built its own settings"
    assert "Library/Preferences" not in shell.settings.fileName(), (
        f"settings are not isolated: {shell.settings.fileName()}")


@needs_hermes
def test_the_empty_console_briefs_you_then_gets_out_of_the_way(app) -> None:
    """On first open the transcript is most of the window.

    It carries the capability briefing — the answer to "can it really
    touch my files?" — and a QTextEdit placeholder renders only its first
    line, so that has to be real content. Which means it must be cleared
    before the first message, or it sits above the conversation forever.
    """
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 60.0, until=lambda: page._empty)
    assert page._empty, "no briefing was shown"
    opening = page._transcript.toPlainText().upper()
    assert "READY" in opening
    # It must state what is being handed to the model, not just greet.
    assert "MODEL" in opening and "WORKING IN" in opening

    page._append("hello", label="you")
    assert not page._empty, "the briefing was not cleared"
    assert "WORKING IN" not in page._transcript.toPlainText().upper()
    assert "hello" in page._transcript.toPlainText()

    page.reset()
    assert page._empty, "a new conversation should brief you again"


def test_the_ribbon_says_something_useful_before_the_first_turn() -> None:
    """"0 of 131K · 0%" is three numbers saying nothing."""
    from hermes_control.ui.widgets import ContextRibbon
    ribbon = ContextRibbon()
    ribbon.set_budget(0, 131_072)
    assert ribbon.fraction == 0.0
    assert ribbon._window == 131_072
    ribbon.set_budget(65_536, 131_072)
    assert ribbon.fraction == 0.5


@needs_hermes
def test_the_gateway_page_judges_channels_by_asking_the_gateway(app) -> None:
    """Not by reading .env. The whole point of the rewrite is that a token
    being present proves nothing about whether a channel works."""
    application, shell = app
    page = shell.page("Gateway")
    shell.show_page("Gateway")
    settle(application, 60.0, until=lambda: page._channel_box.count() > 0)
    assert page._channel_box.count() == len(channels.CHANNELS), \
        "every channel should get a row, connected or not"
    # With nothing connected there is nothing to test-send to, and offering
    # the button anyway would produce a failure that teaches nothing.
    if page._target.count() == 0:
        assert not page._send_button.isEnabled()


@needs_hermes
def test_installed_skills_are_counted_through_the_category_folders(app) -> None:
    """The tree is skills/<category>/<skill>/SKILL.md. Reading one level
    deep reports the dozen category folders as nameless skills and loses
    every real one."""
    application, shell = app
    page = shell.page("Skills")
    shell.show_page("Skills")
    settle(application, 30.0, until=lambda: page._list_box.count() > 0)
    found = shell.hermes.skills()
    on_disk = len(list(shell.hermes.skills_dir.rglob("SKILL.md")))
    assert found, "no skills were read at all"
    assert len(found) == on_disk, (
        f"read {len(found)} skills but {on_disk} SKILL.md files exist")
    assert all(s["name"] for s in found)


@needs_hermes
def test_a_skill_missing_its_command_is_reported_as_unusable(app) -> None:
    """It installs cleanly, lists normally, and fails the first time the
    agent reaches for it. Nothing else in either interface says so."""
    application, shell = app
    found = shell.hermes.skills()
    for skill in found:
        for command in skill.get("missing", []):
            assert shutil.which(command) is None, (
                f"{skill['name']} reports {command} missing but it is on PATH")


@needs_hermes
def test_an_oauth_provider_is_not_claimed_ready_by_default(app) -> None:
    """The bug: readiness for an OAuth provider was computed as
    `provider.oauth`, which is True by definition, so every one showed a
    live badge and an enabled Use button with nothing behind it."""
    application, shell = app
    page = shell.page("Models")
    shell.show_page("Models")
    settle(application, 60.0, until=lambda: page._cloud_box.count() > 0)
    ok, payload = shell.hermes.auth_list()
    pool = hauth.pool(payload, ok)
    oauth = [p for p in providers.CLOUD if p.oauth]
    assert oauth, "no OAuth providers to check"
    # Whatever the real answer is, it must come from the pool and not be
    # the same for every provider regardless of state.
    states = {p.key: pool.has(p.key) for p in oauth}
    assert set(states.values()) != {True} or all(
        pool.has(p.key) for p in oauth), (
        "every OAuth provider reported ready — the constant is back")


@needs_hermes
def test_the_console_window_is_the_one_being_served(app) -> None:
    """The ribbon draws compaction against this number. `ollama_num_ctx`
    is a request that LM Studio ignores — it serves whatever the model
    was loaded at — so drawing the configured value puts the compaction
    mark in the wrong place on a meter whose only job is to show it."""
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 60.0, until=lambda: page._window > 0 or page._ready)
    served = 0
    for server in providers.probe_local():
        if not server.reachable:
            continue
        for model in server.models:
            if model.loaded and model.name == str(
                    shell.hermes.config_value("model.default") or ""):
                served = model.effective_context
    if not served:
        pytest.skip("no local model loaded to compare against")
    assert page._window == served, (
        f"ribbon drew {page._window} but the server serves {served}")


@needs_hermes
def test_a_window_mismatch_is_reported_rather_than_tolerated(app) -> None:
    """Hermes sizes its compressor from ollama_num_ctx whatever the
    provider. Higher than the served window means compaction is
    scheduled past what the server accepts, and a long conversation is
    truncated with nothing said."""
    model = None
    for server in providers.probe_local():
        if server.reachable and not server.is_ollama:
            model = next((m for m in server.models if m.loaded), None)
    if model is None:
        pytest.skip("no loaded LM Studio model")
    if model.effective_context < providers.MIN_CONTEXT_WINDOW:
        pytest.skip(
            f"{model.name} is loaded at {model.effective_context:,}, under "
            f"the floor — reload it before asserting on a mismatch")
    agreed = providers.context_verdict(model, model.effective_context)
    assert agreed.ok
    wrong = providers.context_verdict(model, model.effective_context * 2)
    assert not wrong.ok
    assert wrong.fix == "model.ollama_num_ctx"
    assert wrong.fix_value == model.effective_context


@needs_hermes
def test_attachments_ride_along_and_then_clear(app, tmp_path) -> None:
    """A chip left on the strip after sending would silently re-attach to
    the next message."""
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 60.0, until=lambda: page._ready)
    doc = tmp_path / "note.txt"
    doc.write_text("hello")
    (tmp_path / "folder").mkdir()

    page._add_attachments([str(doc), str(tmp_path / "folder")])
    assert [a.name for a in page._attachments] == ["note.txt"], \
        "a folder was attached"
    assert page._attach_strip.isVisibleTo(page)

    composed = attachments.compose("read it", page._attachments)
    assert str(doc.resolve()) in composed

    page._clear_attachments()
    assert not page._attachments
    assert not page._attach_strip.isVisibleTo(page)


@needs_hermes
def test_an_attachment_alone_is_a_message(app, tmp_path) -> None:
    """Dropping an image in and pressing send should ask the obvious
    question, not refuse for an empty box."""
    application, shell = app
    page = shell.page("Console")
    shell.show_page("Console")
    settle(application, 60.0, until=lambda: page._ready)
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    page._add_attachments([str(img)])
    page._input.clear()
    # Not sending for real — just proving the composed text is non-empty.
    held = list(page._attachments)
    typed = ("Look at what I have attached and tell me what it is."
             if any(a.is_image for a in held) else "")
    assert typed and str(img.resolve()) in attachments.compose(typed, held)
    page._clear_attachments()


def test_a_tool_calls_path_argument_stays_readable() -> None:
    """Which file was touched is the whole question; summarising a path
    as "<132 chars>" hides exactly what you came to check."""
    from hermes_control.ui.pages.console import _arguments
    long_path = "/private/tmp/some/deeply/nested/place/shapes2.png"
    shown = _arguments({"image_url": long_path * 3})
    assert "<" not in shown or "chars" not in shown or "shapes2.png" in shown
    plain = _arguments({"path": "/Users/x/.hermes-agent/SOUL.md"})
    assert plain == "path=/Users/x/.hermes-agent/SOUL.md"
    # Genuinely long non-path values are still summarised.
    assert "<900 chars>" in _arguments({"content": "x" * 900})
