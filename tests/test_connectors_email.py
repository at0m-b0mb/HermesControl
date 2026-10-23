"""
Tests for connectors and the email gateway.

Neither can be fully exercised without the user's own accounts — a Portal
sign-in and a mailbox password are theirs, and this app never supplies them.
What is testable is everything up to that point: the parsing, the diagnosis
that one missing sign-in explains every disconnected app, the provider
settings nobody should have to look up, and the staged connection check that
turns "it does not work" into a named failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import email as mail  # noqa: E402
from hermes_control.cli import Hermes  # noqa: E402
from hermes_control.connectors import Connector, Connectors, Portal  # noqa: E402

HERMES = Hermes()
needs_hermes = pytest.mark.skipif(
    not HERMES.installed, reason="no managed Hermes Agent")


# --- connectors -------------------------------------------------------------

def test_a_connector_gets_a_readable_label() -> None:
    assert Connector("clickhouse_mcp", False).label == "Clickhouse"
    assert Connector("adobe_marketing_agent_mcp", False).label == \
        "Adobe Marketing Agent"
    assert Connector("jira", False).label == "Jira"


def test_portal_knows_when_it_is_the_blocker() -> None:
    assert Portal(logged_in=False).blocks_connectors
    assert not Portal(logged_in=True).blocks_connectors


@needs_hermes
def test_the_catalogue_parses_into_real_entries() -> None:
    catalogue = Connectors(HERMES).catalogue()
    assert len(catalogue) > 10, "the connector listing did not parse"
    for connector in catalogue:
        assert connector.name and " " not in connector.name
        assert isinstance(connector.connected, bool)
    # Banner lines must never become connectors called "You" or "-".
    assert not any(c.name.lower() in ("you", "-", "=") for c in catalogue)


@needs_hermes
def test_portal_status_is_parsed() -> None:
    portal = Connectors(HERMES).portal()
    assert portal.raw, "portal status returned nothing"
    assert isinstance(portal.logged_in, bool)


# --- email ------------------------------------------------------------------

def test_every_provider_has_usable_settings() -> None:
    for provider in mail.PROVIDERS:
        if provider.label == "Custom":
            continue
        assert provider.imap_host and provider.smtp_host, provider.label
        assert 1 <= provider.imap_port <= 65535
        assert 1 <= provider.smtp_port <= 65535
        assert provider.note, (
            f"{provider.label} needs an app password; say so before the "
            f"attempt rather than after a confusing refusal")


@pytest.mark.parametrize("address,expected", [
    ("someone@gmail.com", "Gmail"),
    ("someone@googlemail.com", "Gmail"),
    ("a.b@icloud.com", "iCloud"),
    ("x@me.com", "iCloud"),
    ("x@outlook.com", "Outlook / Microsoft 365"),
    ("x@hotmail.com", "Outlook / Microsoft 365"),
    ("x@fastmail.com", "Fastmail"),
])
def test_the_provider_is_guessed_from_the_address(address, expected) -> None:
    guess = mail.guess_provider(address)
    assert guess is not None and guess.label == expected


@pytest.mark.parametrize("address", ["", "nodomain", "x@an-unknown-host.tld"])
def test_an_unknown_address_guesses_nothing(address) -> None:
    assert mail.guess_provider(address) is None


def test_the_required_variables_match_the_plugin() -> None:
    """These are the plugin's own requires_env names; a typo breaks silently."""
    assert mail.REQUIRED == ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST")
    for name in mail.REQUIRED + mail.OPTIONAL:
        assert name.isupper(), (
            f"{name} must be UPPER_SNAKE so Hermes routes it to .env rather "
            f"than config.yaml")


def test_the_password_variable_is_marked_secret() -> None:
    assert "EMAIL_PASSWORD" in mail.SECRET
    from hermes_control import confschema
    assert confschema.is_secret("EMAIL_PASSWORD")


def test_a_check_with_no_hosts_says_so_rather_than_passing() -> None:
    result = mail.check("a@b.c", "x", "", 993, "", 587)
    assert not result.ok
    assert result.first_failure is not None
    assert "nothing to test" in result.first_failure.detail


def test_a_bad_hostname_fails_at_the_first_stage() -> None:
    """Staged checks exist so a failure names the part that failed."""
    result = mail.check("a@b.c", "x", "imap.nowhere.invalid", 993, "", 587)
    assert not result.ok
    failure = result.first_failure
    assert failure is not None
    assert failure.name.startswith("Reach")
    assert "does not resolve" in failure.detail


@pytest.mark.parametrize("message,expected", [
    ("Application-specific password required", "app password"),
    ("Invalid credentials (Failure)", "app password"),
    ("LOGIN failed: IMAP access is disabled", "switched off"),
])
def test_auth_failures_are_translated_into_the_real_cause(message, expected) -> None:
    assert expected in mail._auth_hint(message)


def test_the_password_never_appears_in_a_failure_message() -> None:
    """A credential in an error string ends up in a log or a screenshot."""
    secret = "sup3r-s3cret-app-password"
    result = mail.check("a@b.c", secret, "imap.nowhere.invalid", 993,
                        "smtp.nowhere.invalid", 587)
    blob = " ".join(f"{s.name} {s.detail}" for s in result.stages)
    assert secret not in blob
