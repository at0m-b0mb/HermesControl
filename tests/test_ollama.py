"""
Tests for the Ollama client.

The parts worth pinning down are the ones that would quietly mislead: the
progress arithmetic, and the claim that every suggested model clears Hermes's
floor. That last one is a promise printed on the page, so it should be a test
rather than a hope.

Network-touching tests skip when Ollama is not running.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import providers  # noqa: E402
from hermes_control.ollama import (  # noqa: E402
    KNOWN_TOO_SMALL, SUGGESTED, Ollama, PullProgress,
)

LIVE = Ollama()
needs_ollama = pytest.mark.skipif(not LIVE.reachable, reason="Ollama is not running")


def test_every_suggestion_clears_the_floor() -> None:
    """The card says so in as many words, so it had better be true."""
    for suggestion in SUGGESTED:
        assert suggestion.published_context >= providers.MIN_CONTEXT_WINDOW, (
            f"{suggestion.name} is suggested but its published window "
            f"({suggestion.published_context:,}) is under the floor")
        assert suggestion.clears_floor


def test_the_warning_list_really_is_too_small() -> None:
    for name, window in KNOWN_TOO_SMALL:
        assert window < providers.MIN_CONTEXT_WINDOW, name


def test_suggestions_are_distinct_and_described() -> None:
    names = [s.name for s in SUGGESTED]
    assert len(names) == len(set(names))
    for suggestion in SUGGESTED:
        assert suggestion.note.strip(), f"{suggestion.name} has no reason given"
        assert suggestion.size_hint.strip()


def test_progress_fraction_is_bounded() -> None:
    assert PullProgress("x", 0, 0).fraction == 0.0
    assert PullProgress("x", 50, 100).fraction == 0.5
    assert PullProgress("x", 100, 100).fraction == 1.0
    # Ollama has been seen to report completed > total on a resumed layer.
    assert PullProgress("x", 150, 100).fraction == 1.0
    assert PullProgress("x", 5, 0).fraction == 0.0


def test_progress_knows_when_it_is_done() -> None:
    assert PullProgress("success").done
    assert not PullProgress("pulling manifest").done


def test_an_unreachable_host_degrades_quietly() -> None:
    """A wrong port must give empty answers, never an exception."""
    dead = Ollama("http://127.0.0.1:9")
    assert dead.version() is None
    assert dead.reachable is False
    assert dead.installed() == []
    assert dead.resident() == []
    assert dead.context_window("anything") == 0
    ok, message = dead.delete("anything")
    assert ok is False and message


def test_a_failed_pull_yields_an_error_rather_than_raising() -> None:
    dead = Ollama("http://127.0.0.1:9")
    events = list(dead.pull("whatever", timeout=3))
    assert events, "a failed pull must still report something"
    assert events[-1].error, "the failure must be visible to the caller"
    assert events[-1].status == "failed"


@needs_ollama
def test_live_version_and_listing() -> None:
    assert LIVE.version()
    assert isinstance(LIVE.installed(), list)
    assert isinstance(LIVE.resident(), list)


@needs_ollama
def test_context_window_is_read_from_the_model() -> None:
    installed = LIVE.installed()
    if not installed:
        pytest.skip("no models installed")
    windows = {name: LIVE.context_window(name) for name in installed}
    assert any(w > 0 for w in windows.values()), (
        f"no model reported a context window: {windows}")


@needs_ollama
def test_deleting_something_that_does_not_exist_is_reported() -> None:
    ok, message = LIVE.delete("hermes-control-test-nonexistent:zzz")
    assert ok is False
    assert "not found" in message.lower() or "404" in message


# --- tool support -----------------------------------------------------------

def test_no_suggestion_is_on_the_no_tools_list() -> None:
    """deepseek-r1 was suggested here until it was actually tried.

    It has a 131K window and chats perfectly well, so every check this app
    made said it was fine — and every turn failed with HTTP 400 before a
    token, because Hermes sends a tool list on every request.
    """
    from hermes_control.ollama import KNOWN_NO_TOOLS
    for suggestion in SUGGESTED:
        stem = suggestion.name.split(":")[0]
        assert stem not in KNOWN_NO_TOOLS, (
            f"{suggestion.name} cannot use tools and must not be suggested")


@needs_ollama
def test_capabilities_are_read_from_ollama() -> None:
    from hermes_control.providers import probe_ollama
    server = probe_ollama()
    if not server.models:
        pytest.skip("no models installed")
    assert any(m.capabilities for m in server.models), (
        "no model reported capabilities; tool support cannot be judged")


@needs_ollama
def test_tool_support_matches_what_ollama_reports() -> None:
    import httpx
    from hermes_control.providers import probe_ollama
    for model in probe_ollama().models:
        if model.supports_tools is None:
            continue
        payload = httpx.post("http://localhost:11434/api/show",
                             json={"model": model.name}, timeout=20).json()
        caps = payload.get("capabilities") or []
        assert model.supports_tools == ("tools" in caps), model.name
