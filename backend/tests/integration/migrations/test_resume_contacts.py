"""Migration 0042 reads a stored contact line into typed items and back
(ADR 0048), with its own copy of the rule."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from advisor.resume.domain import get_contact_items

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20261013_0042_resume_contacts.py"
)
LINE = "maya@example.com · +49 151 2345 6789 · github.com/mayalin · Berlin"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0042", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_stored_line_becomes_the_items_the_app_reads_and_goes_back() -> None:
    migration = _load()

    items = migration.to_items(LINE)

    assert items == [c.to_dict() for c in get_contact_items(LINE)]
    assert migration.to_line(items) == LINE
    assert migration.to_items("") == []
