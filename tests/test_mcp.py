"""
Tests for the MCP surface.

The parsing is the risk: the catalogue is a plain-text table, and a loose
regex turns its rule line into a server called "------". The other thing
worth pinning is the orientation card, which exists to answer "why is there
no email connector" and would be worse than useless if it went stale.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control.cli import Hermes  # noqa: E402
from hermes_control.mcp import WHERE_THINGS_LIVE, Mcp, Server  # noqa: E402

HERMES = Hermes()
needs_hermes = pytest.mark.skipif(not HERMES.installed, reason="no Hermes")


def test_a_server_knows_whether_it_is_installed() -> None:
    assert not Server("linear", "available").installed
    assert Server("linear", "configured").installed
    assert Server("aws-knowledge", "available").label == "Aws Knowledge"


def test_the_orientation_card_states_no_counts() -> None:
    """A number in this card goes stale the moment a catalogue changes."""
    import re
    for name, detail in WHERE_THINGS_LIVE:
        assert not re.search(r"\b\d{2,}\b", detail), (
            f"{name} hardcodes a count that will drift: {detail!r}")


def test_the_card_separates_the_two_directions_of_email() -> None:
    """The question this page exists to answer, and the one that is
    answered wrongly most often: being emailed and reading email are
    different surfaces, and the obvious place has neither of them."""
    where = dict(WHERE_THINGS_LIVE)
    inbound = where["Email, inbound"]
    outbound = where["Email, outbound"]
    assert "Gateway" in inbound
    assert "skill" in outbound.lower()
    assert "not a connector" in outbound.lower()
    # It must not send the reader to this catalogue, which is where they
    # already looked.
    assert "not in this catalogue" in outbound.lower()


@needs_hermes
def test_the_catalogue_parses_cleanly() -> None:
    servers = Mcp(HERMES).catalogue()
    assert len(servers) > 20, "the catalogue did not parse"
    for server in servers:
        assert server.name and " " not in server.name
        assert set(server.name) != {"-"}, "a table rule became a server"
        assert server.name.lower() != "name", "the header became a server"
        assert server.description, f"{server.name} has no description"


@needs_hermes
def test_nothing_is_reported_configured_that_is_not() -> None:
    mcp = Mcp(HERMES)
    configured = set(mcp.configured())
    flagged = {s.name for s in mcp.catalogue() if s.installed}
    assert flagged <= configured | set(), (
        f"catalogue says installed but `mcp list` disagrees: "
        f"{flagged - configured}")


# --- channels: three states that look alike from outside -------------------

from hermes_control import channels, hub  # noqa: E402


def _env(**kw) -> dict[str, str]:
    return {k: v for k, v in kw.items()}


def test_an_empty_listing_is_an_answer_not_a_failure():
    """Nothing connected is a real state; it must not read as an error."""
    assert channels.parse_targets('{"platforms": {}}') == {}
    survey = channels.survey({}, '{"platforms": {}}', True)
    assert survey.listed and not survey.live
    assert all(s.state == "off" for s in survey.states)


def test_configured_but_unreachable_is_distinguished_from_unconfigured():
    """The commonest real failure: a token written and the gateway never
    restarted. Reporting it as "not configured" sends the user to paste a
    token they already pasted."""
    env = _env(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_ALLOWED_USERS="7")
    survey = channels.survey(env, '{"platforms": {}}', True)
    telegram = next(s for s in survey.states if s.channel.key == "telegram")
    assert telegram.state == "broken"
    assert "restart" in telegram.detail.lower()


def test_connected_with_an_empty_allowlist_is_called_out():
    """It connects, receives the message, and ignores it in silence —
    which looks exactly like the bot being broken."""
    env = _env(TELEGRAM_BOT_TOKEN="123:abc")
    survey = channels.survey(env, '{"platforms": {"telegram": ["home"]}}', True)
    telegram = next(s for s in survey.states if s.channel.key == "telegram")
    assert telegram.state == "blocked"
    assert "TELEGRAM_ALLOWED_USERS" in telegram.detail


def test_a_channel_the_gateway_can_reach_is_live():
    env = _env(TELEGRAM_BOT_TOKEN="x", TELEGRAM_ALLOWED_USERS="7")
    survey = channels.survey(env, '{"platforms": {"telegram": ["home"]}}', True)
    telegram = next(s for s in survey.states if s.channel.key == "telegram")
    assert telegram.state == "live" and telegram.deliverable
    assert survey.live == [telegram]


def test_a_target_is_a_record_not_a_string():
    """Telegram answers with dicts. Reading them as strings put the whole
    repr in the menu and then handed that repr to `send -t`, which cannot
    address anything with it."""
    payload = ('{"platforms": {"telegram": [{"id": "5522781788", '
               '"name": "King Krish", "type": "dm", "thread_id": null}]}}')
    found = channels.parse_targets(payload)["telegram"]
    assert len(found) == 1
    target = found[0]
    assert target.ident == "5522781788"
    assert target.address == "telegram:5522781788"
    assert target.label == "King Krish (dm)"


def test_bare_string_targets_still_work():
    """Older versions list ids rather than records."""
    found = channels.parse_targets('{"platforms": {"slack": ["C0123"]}}')["slack"]
    assert found[0].address == "slack:C0123"


def test_a_platform_with_no_discovered_chats_is_still_live():
    """On Telegram no chat exists until someone has messaged the bot, so
    an empty list means "nothing discovered yet", not "unreachable"."""
    env = _env(TELEGRAM_BOT_TOKEN="x", TELEGRAM_ALLOWED_USERS="7")
    survey = channels.survey(env, '{"platforms": {"telegram": []}}', True)
    telegram = next(s for s in survey.states if s.channel.key == "telegram")
    assert telegram.state == "live" and not telegram.targets


def test_slack_needs_both_tokens_and_says_which_is_missing():
    survey = channels.survey(_env(SLACK_BOT_TOKEN="xoxb-x"),
                             '{"platforms": {}}', True)
    slack = next(s for s in survey.states if s.channel.key == "slack")
    assert "SLACK_APP_TOKEN" in slack.headline


def test_without_a_listing_nothing_is_asserted():
    """Every verdict here depends on the gateway's answer. Without it the
    page must say so rather than print a confident 'not connected'."""
    survey = channels.survey(_env(TELEGRAM_BOT_TOKEN="x"), "", False, "boom")
    assert not survey.listed
    assert all(s.state == "unknown" for s in survey.states)


def test_allow_all_suppresses_the_empty_allowlist_warning():
    env = _env(TELEGRAM_BOT_TOKEN="x", GATEWAY_ALLOW_ALL_USERS="true")
    survey = channels.survey(env, '{"platforms": {"telegram": []}}', True)
    assert survey.allow_all
    telegram = next(s for s in survey.states if s.channel.key == "telegram")
    assert telegram.state == "live"


def test_garbage_from_the_cli_does_not_raise():
    for junk in ("", "not json", "[]", '{"platforms": 3}'):
        assert channels.parse_targets(junk) == {}


# --- the skills hub --------------------------------------------------------

def test_search_results_are_parsed_with_their_full_identifier():
    """The table truncates identifiers to the column width, and the
    identifier is what install needs — so only the JSON is usable."""
    payload = """[{"name": "Himalaya", "identifier": "himalaya-skill",
                   "source": "clawhub", "trust_level": "community",
                   "description": "IMAP/SMTP mail."}]"""
    found = hub.parse_search(payload)
    assert len(found) == 1
    assert found[0].identifier == "himalaya-skill"
    assert not found[0].official


def test_official_skills_rank_above_placeholder_descriptions():
    rows = [hub.Skill("z", "z", "skills.sh", "community",
                      "Indexed by skills.sh from someone/repo"),
            hub.Skill("a", "a", "clawhub", "community", "Does a real thing."),
            hub.Skill("m", "m", "official", "official", "Official one.")]
    assert [s.identifier for s in hub.rank(rows)] == ["m", "a", "z"]


def test_a_row_without_an_identifier_is_dropped():
    assert hub.parse_search('[{"name": "x"}, {"description": "y"}]') == \
        hub.parse_search('[{"name": "x"}]')


def test_hub_parser_survives_junk():
    for junk in ("", "null", "{}", "[1, 2]", "not json"):
        assert hub.parse_search(junk) == []
