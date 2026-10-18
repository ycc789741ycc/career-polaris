"""A place whose image is older than the schema refuses to migrate (ADR 0051).

The edge migrates first in a release; a compute machine still on the previous
image must stop at its start instead of running against tables it predates.
"""

from __future__ import annotations

import pytest

from cli.migrate import SchemaAheadError, assert_schema_known, get_schema_report, main

KNOWN = {"0042_resume_contacts", "0043_more_resume_fonts"}


def test_a_database_at_a_known_revision_passes() -> None:
    assert_schema_known(["0043_more_resume_fonts"], KNOWN)


def test_a_fresh_database_passes() -> None:
    assert_schema_known([], KNOWN)


def test_a_database_a_newer_release_migrated_is_refused() -> None:
    with pytest.raises(SchemaAheadError, match="0044_from_the_future"):
        assert_schema_known(["0044_from_the_future"], KNOWN)


def test_the_check_names_the_revision_an_image_can_run_on() -> None:
    assert get_schema_report(["0043_more_resume_fonts"], KNOWN) == (
        "schema: at 0043_more_resume_fonts, which this image knows"
    )


def test_the_check_says_an_empty_database_is_created_by_the_migrations() -> None:
    assert "empty" in get_schema_report([], KNOWN)


def test_the_check_refuses_a_schema_a_newer_release_migrated() -> None:
    with pytest.raises(SchemaAheadError, match="0044_from_the_future"):
        get_schema_report(["0044_from_the_future"], KNOWN)


def test_an_unknown_argument_is_refused_before_anything_is_read() -> None:
    with pytest.raises(SystemExit, match="usage"):
        main(["--force"])
