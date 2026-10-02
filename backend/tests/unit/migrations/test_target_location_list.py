"""Migration 0021 moves free-text target locations onto the list (ADR 0026).

Its mapping is frozen in the migration, so this checks it against the list as
it stands: every place it writes is one ``set_target_locations`` accepts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from advisor.market.domain import target_location_option

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20261002_0021_target_location_list.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0021", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()


@pytest.mark.parametrize(
    ("stored", "place"),
    [
        ("UK", "United Kingdom"),
        ("united kingdom", "United Kingdom"),
        ("Remote Taiwan", "Taiwan"),
        ("Taiwan (remote)", "Taiwan"),
        ("Remote EU", "Europe"),
        ("EU", "Europe"),
        ("Remote", "Remote"),
        ("Worldwide", "Remote"),
        ("APAC", "Asia-Pacific"),
        ("Korea", "South Korea"),
        ("Deutschland", "Germany"),
    ],
)
def test_a_stored_location_moves_to_the_place_it_names(stored: str, place: str) -> None:
    assert migration.place_for(stored) == place


@pytest.mark.parametrize("stored", ["Taipei", "Berlin, Germany", "Remote APAC-ish", "Mars", ""])
def test_a_city_or_an_unknown_place_maps_to_nothing(stored: str) -> None:
    """Deleted by the migration: a city is not on the list (ADR 0026)."""
    assert migration.place_for(stored) is None


def test_every_place_the_migration_writes_is_on_the_list() -> None:
    for place in set(migration._PLACES.values()):
        option = target_location_option(place)
        assert option is not None and option.name == place
