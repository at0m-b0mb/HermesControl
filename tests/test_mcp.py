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


def test_the_card_says_where_email_actually_is() -> None:
    """The question this page exists to answer."""
    email = dict(WHERE_THINGS_LIVE)["Email"]
    assert "Gateway" in email
    assert "not a connector" in email.lower()


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
