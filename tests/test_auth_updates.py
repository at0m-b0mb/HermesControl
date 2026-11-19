"""
Credentials, briefings and updates — the three places this app used to
state something it had not checked.
"""

from __future__ import annotations

from hermes_control import auth, briefing, updates

AUTH_LISTING = """copilot (1 credentials):
  #1  gh auth token        api_key id=b7866d priority=0 gh_cli ←

nous (2 credentials):
  #1  you@example.com      oauth   id=095dbe priority=0 device_code ←
  #2  other@example.com    oauth   id=11aa22 priority=1 device_code
"""


# --- auth -------------------------------------------------------------------

def test_the_pool_is_read_rather_than_inferred():
    """The bug this replaces: an OAuth provider's readiness was computed
    as `provider.oauth`, a constant, so every one of them showed a live
    badge and an enabled Use button whether or not anyone had signed in."""
    pool = auth.pool(AUTH_LISTING, True)
    assert pool.providers == ["copilot", "nous"]
    assert pool.has("nous") and pool.has("copilot")
    assert not pool.has("openai-codex")


def test_a_label_with_spaces_survives_the_parse():
    pool = auth.pool(AUTH_LISTING, True)
    copilot = pool.for_provider("copilot")[0]
    assert copilot.label == "gh auth token"
    assert copilot.kind == "api_key" and not copilot.is_oauth


def test_the_active_credential_is_marked():
    first, second = auth.pool(AUTH_LISTING, True).for_provider("nous")
    assert first.active and not second.active
    assert first.is_oauth


def test_an_unreadable_listing_claims_nothing():
    """Reporting every provider as signed out because the listing failed
    would be a confident wrong answer."""
    pool = auth.pool("", False, "boom")
    assert not pool.read and not pool.credentials and pool.error == "boom"


def test_nous_signs_in_through_upgrade_not_add():
    """`auth upgrade` keeps connectors already attached to the account;
    `auth add nous` does not."""
    assert auth.sign_in_argv("nous") == ["auth", "upgrade"]
    assert "--no-browser" in auth.sign_in_argv("openai-codex")
    # An unknown provider still gets a sensible, printable flow.
    assert auth.sign_in_argv("whatever")[:3] == ["auth", "add", "whatever"]


def test_the_device_code_is_pulled_out_of_the_stream():
    text = ("Open https://auth.example.com/device and enter code: ABCD-1234\n")
    url, code = auth.extract_code(text)
    assert url == "https://auth.example.com/device"
    assert code == "ABCD-1234"


def test_junk_output_yields_no_false_code():
    assert auth.extract_code("nothing useful here") == ("", "")


# --- briefing ---------------------------------------------------------------

PROMPT_SIZE = """Prompt-size breakdown (platform=cli, model=x)

  System prompt total :   18,556 B  (18.1 KB, 18,464 chars)

  Tool schemas         :   41,142 B  (40.2 KB, 21 tools)

  Toolsets by size (tool-schema JSON, largest first):
    toolset                tools      schema
    file                       4     5,673 B  (5.5 KB)
    vision                     1       845 B  (0.8 KB)
    terminal                   1     2,741 B  (2.7 KB)

  Skills by size (SKILL.md on-disk = read cost):
    claude-code                    35,175 B        70 B
"""


def test_the_tool_count_is_read_from_inside_its_own_bracket():
    """`(40.2 KB, 21 tools)` puts the count in the same bracket as the
    rounded size, so a pattern anchored on "(" finds "40.2 KB" and
    reports zero tools — which read as an agent with none."""
    b = briefing.build(PROMPT_SIZE, True, window=65_536)
    assert b.tool_count == 21
    assert b.schema_bytes == 41_142
    assert b.prompt_bytes == 18_556


def test_capabilities_come_from_the_schemas_being_sent():
    b = briefing.build(PROMPT_SIZE, True)
    assert b.can_edit_files and b.can_see_images and b.can_run_commands
    assert [t.name for t in b.toolsets] == ["file", "vision", "terminal"]
    assert b.toolsets[0].plain.startswith("read, write")


def test_headroom_subtracts_what_is_sent_before_you_speak():
    """A 65,536-token window carrying 60 KB of prompt and schemas has far
    less room for the conversation than its headline number suggests."""
    b = briefing.build(PROMPT_SIZE, True, window=65_536)
    assert b.overhead == 18_556 + 41_142
    assert 0 < b.headroom() < 65_536


def test_an_unread_briefing_claims_no_tools():
    b = briefing.build("", False, error="nope")
    assert not b.read and not b.toolsets
    assert not b.can_edit_files


# --- updates ----------------------------------------------------------------

def test_up_to_date_is_distinguished_from_unknown():
    current = updates.parse_hermes_check(
        "→ Update channel: stable\n"
        "✓ Up to date with the latest release (stable v0.23.2 (ae2a81c)).",
        installed="0.23.2")
    assert current.state == "current" and current.channel == "stable"

    unknown = updates.parse_hermes_check("", installed="0.23.2", ok=False)
    # Not "current": a check that could not run has not said anything.
    assert unknown.state == "unknown"


def test_an_available_update_is_reported_with_its_version():
    row = updates.parse_hermes_check("Update available: v0.24.0")
    assert row.state == "behind" and row.latest == "0.24.0"


def test_skill_counts_are_read_and_qualified():
    none = updates.parse_skills_check("0 update(s) available across 6 checked skill(s)")
    assert none.state == "current"
    # Bundled and self-written skills are not in that count, and saying
    # "all skills are current" would overclaim.
    assert "bundled" in none.detail.lower()
    some = updates.parse_skills_check("2 update(s) available across 6 checked skill(s)")
    assert some.state == "behind" and "2 of 6" in some.detail


def test_version_comparison_refuses_to_guess():
    assert updates.compare_versions("1.9.1", "1.10.0") is True
    assert updates.compare_versions("1.10.0", "1.10.0") is False
    assert updates.compare_versions("1.10.1", "1.10.0") is False
    # Short and long forms compare properly rather than by string length.
    assert updates.compare_versions("1.2", "1.2.1") is True
    # And anything unparseable is unknown, never "an update is available".
    for bad in (("", "1.0"), ("dev", "1.0"), ("1.0", "nightly")):
        assert updates.compare_versions(*bad) is None


# --- attachments ------------------------------------------------------------

from pathlib import Path  # noqa: E402

from hermes_control import attachments  # noqa: E402


def test_folders_and_missing_files_are_dropped(tmp_path):
    """Dropping a folder on a chat window must not quietly enqueue
    everything inside it."""
    real = tmp_path / "a.txt"
    real.write_text("x")
    (tmp_path / "sub").mkdir()
    found = attachments.collect([real, tmp_path / "sub", tmp_path / "nope.txt"])
    assert [a.name for a in found] == ["a.txt"]


def test_the_same_file_twice_is_attached_once(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert len(attachments.collect([f, f, str(f)])) == 1


def test_images_are_distinguished_from_other_files(tmp_path):
    img = tmp_path / "pic.PNG"
    img.write_bytes(b"\x89PNG")
    doc = tmp_path / "notes.md"
    doc.write_text("x")
    found = {a.name: a for a in attachments.collect([img, doc])}
    assert found["pic.PNG"].is_image and found["pic.PNG"].kind == "image"
    assert not found["notes.md"].is_image
    assert found["notes.md"].kind == "Markdown"


def test_the_prompt_names_every_path_absolutely(tmp_path):
    """Hermes's --image flag is refused whenever a gateway is running, so
    attachments travel as absolute paths in the prompt. A relative one
    would resolve against a working directory that is nobody's."""
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    doc = tmp_path / "notes.txt"
    doc.write_text("hello")
    found = attachments.collect([img, doc])
    prompt = attachments.compose("what is this", found)
    for item in found:
        assert str(item.path) in prompt
        assert Path(str(item.path)).is_absolute()
    assert "vision_analyze" in prompt
    assert "read_file" in prompt


def test_a_prompt_without_attachments_is_untouched():
    assert attachments.compose("just a question", []) == "just a question"


def test_a_large_file_is_flagged_rather_than_silently_read(tmp_path):
    big = tmp_path / "big.log"
    big.write_text("x" * (attachments.LARGE_FILE_BYTES + 10))
    prompt = attachments.compose("summarise", attachments.collect([big]))
    assert "large" in prompt.lower()


def test_an_image_mentions_vision_and_not_read_file(tmp_path):
    img = tmp_path / "pic.jpg"
    img.write_bytes(b"\xff\xd8")
    prompt = attachments.compose("look", attachments.collect([img]))
    assert "vision_analyze" in prompt
    assert "read_file" not in prompt
