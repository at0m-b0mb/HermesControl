"""
Tests for the schema parser.

The parser's job is to read Hermes's annotated config and lose nothing, so
these check the two failure modes that would matter: dropping a real setting,
and inventing one out of a sentence that happens to contain a colon.

They run against a fixture rather than the live install, so they pass on a
machine with no Hermes on it.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_control import confschema  # noqa: E402

SAMPLE = textwrap.dedent('''\
    # Hermes Agent CLI Configuration
    _config_version: 51

    # =============================================================================
    # Database Configuration
    # =============================================================================
    # WAL is the normal default. Hermes falls back to DELETE when SQLite says
    # WAL is incompatible with the filesystem.
    database:
      journal_mode: "wal"  # Supported values: "wal", "delete"
      # Optional WAL sizing pragmas (integers). Unset = SQLite defaults.
      # wal_autocheckpoint: 1000     # pages between automatic checkpoints
      #
      # Note: this sentence mentions a colon but is not a setting.
      # synchronous: FULL

    # =============================================================================
    # Context Compression
    # =============================================================================
    compression:
      enabled: true
      threshold: 0.50
      protect_last_n: 20
      tail_mode: lean
    ''')


@pytest.fixture()
def schema(tmp_path: Path) -> confschema.Schema:
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    return confschema.parse(path)


def test_reads_the_schema_version(schema: confschema.Schema) -> None:
    assert schema.config_version == 51


def test_finds_active_settings_with_dotted_paths(schema: confschema.Schema) -> None:
    paths = {o.path for o in schema.options}
    assert "database.journal_mode" in paths
    assert "compression.threshold" in paths
    assert "compression.protect_last_n" in paths


def test_version_marker_is_not_offered_as_a_setting(schema: confschema.Schema) -> None:
    """Hermes manages _config_version; exposing it invites corruption."""
    assert schema.get("_config_version") is None


def test_types_come_from_the_real_values(schema: confschema.Schema) -> None:
    assert schema.get("compression.enabled").kind == "bool"
    assert schema.get("compression.threshold").kind == "float"
    assert schema.get("compression.protect_last_n").kind == "int"


def test_inline_supported_values_become_choices(schema: confschema.Schema) -> None:
    option = schema.get("database.journal_mode")
    assert option.kind == "choice"
    assert option.choices == ["wal", "delete"]


def test_commented_settings_are_found_but_marked_unset(schema: confschema.Schema) -> None:
    option = schema.get("database.wal_autocheckpoint")
    assert option is not None, "a commented-out option is still an option"
    assert option.commented is True
    assert option.value is None
    assert option.default == 1000


def test_prose_is_not_mistaken_for_a_setting(schema: confschema.Schema) -> None:
    """`# Note: ...` is a sentence, not `note: ...`."""
    assert schema.get("database.note") is None
    assert schema.get("note") is None


def test_sections_come_from_the_banners(schema: confschema.Schema) -> None:
    assert "Database Configuration" in schema.sections
    assert "Context Compression" in schema.sections
    assert schema.get("compression.enabled").section == "Context Compression"


def test_help_text_is_carried_over(schema: confschema.Schema) -> None:
    """Prose above `database:` documents the group, so it lands on the group.

    This is worth pinning down: the Config page hides container keys whose
    children it is already showing, so if their help were dropped rather than
    re-surfaced as a section preamble, this text would vanish from the UI.
    """
    assert "WAL is the normal default" in schema.get("database").help
    assert schema.get("database.journal_mode").inline.startswith("Supported values")


def test_search_matches_key_section_and_help(schema: confschema.Schema) -> None:
    assert any(o.path == "database.journal_mode" for o in schema.search("journal"))
    assert any(o.path == "compression.enabled" for o in schema.search("compression"))
    assert schema.search("definitely-not-present") == []


def test_parsing_the_installed_config_if_there_is_one() -> None:
    """Belt and braces: if a real Hermes is here, its config must parse."""
    live = Path.home() / ".hermes-agent" / "config.yaml"
    if not live.exists():
        pytest.skip("no managed Hermes install on this machine")
    parsed = confschema.parse(live)
    assert len(parsed.options) > 100, "a real config should yield many options"
    assert len(parsed.sections) > 10
    assert all("." in o.path or o.path.islower() for o in parsed.options)
