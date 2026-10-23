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


# --- the provider value we write --------------------------------------------

#: Hermes's own doctor rejects anything outside its canonical list. The three
#: local aliases work at run time and fail that check, which is how a working
#: setup ends up reporting a problem the user cannot find.
DOCTOR_REJECTS = ("ollama", "vllm", "llamacpp")


def test_we_never_write_an_alias_as_the_provider() -> None:
    from hermes_control import providers
    assert providers.probe_ollama().provider_key not in DOCTOR_REJECTS
    for alias in DOCTOR_REJECTS:
        assert providers.canonical_provider(alias) == "custom"
    # lmstudio is itself canonical and must survive unchanged.
    assert providers.canonical_provider("lmstudio") == "lmstudio"


def test_aliases_are_still_recognised_as_local() -> None:
    """Someone's existing config may hold an alias; the UI must not call it hosted."""
    from hermes_control import providers
    for alias in DOCTOR_REJECTS:
        assert providers.is_local(alias)
    assert providers.is_local("custom")
    assert not providers.is_local("openrouter")


def test_neither_page_writes_the_alias() -> None:
    """Grep the two call sites, since this is a value not a code path."""
    root = Path(__file__).resolve().parents[1] / "hermes_control" / "ui" / "pages"
    for name in ("models.py", "setup.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert '"model.provider": "ollama"' not in source, (
            f"{name} writes the alias, which makes hermes doctor report a "
            f"problem on a working setup")


# --- how big a window to ask for --------------------------------------------

def test_a_large_model_is_not_asked_for_a_huge_window() -> None:
    """num_ctx sizes the KV cache, which is allocated up front.

    Asking a 30B for 131,072 tokens killed the Ollama runner mid-turn with
    "model runner has unexpectedly stopped ... resource limitations", and
    Hermes retried straight into the same wall. The floor is the default;
    headroom is opt-in.
    """
    from hermes_control.providers import (
        DEFAULT_NUM_CTX, LocalModel, MIN_CONTEXT_WINDOW, suggested_num_ctx,
    )
    big = LocalModel(name="qwen3:30b-a3b", server="Ollama",
                     context=262_144, size_bytes=18_600_000_000)
    assert suggested_num_ctx(big) == DEFAULT_NUM_CTX
    assert suggested_num_ctx(big) >= MIN_CONTEXT_WINDOW


def test_a_small_model_still_gets_headroom() -> None:
    from hermes_control.providers import (
        GENEROUS_NUM_CTX, LocalModel, suggested_num_ctx,
    )
    small = LocalModel(name="llama3.2:1b", server="Ollama",
                       context=131_072, size_bytes=1_300_000_000)
    assert suggested_num_ctx(small) == GENEROUS_NUM_CTX


def test_we_never_ask_for_more_than_the_model_has() -> None:
    """Ollama sends an explicit num_ctx as-is, so an over-ask is a silent lie."""
    from hermes_control.providers import LocalModel, suggested_num_ctx
    for size in (1_000_000_000, 20_000_000_000):
        model = LocalModel(name="x", server="Ollama", context=70_000,
                           size_bytes=size)
        assert suggested_num_ctx(model) <= model.context


def test_an_unknown_window_still_clears_the_floor() -> None:
    from hermes_control.providers import (
        LocalModel, MIN_CONTEXT_WINDOW, suggested_num_ctx,
    )
    model = LocalModel(name="x", server="Ollama", context=0, size_bytes=0)
    assert suggested_num_ctx(model) >= MIN_CONTEXT_WINDOW
