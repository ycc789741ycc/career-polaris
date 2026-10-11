"""Migration 0056 (ADR 0073): an opening's fit lives in Target, behind RLS,
and the fits builds worked out from embedding similarity are gone."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from kernel.db import Database

pytestmark = pytest.mark.integration

_NEW = ("target.opening_requirement", "target.opening_requirement_fit", "target.opening_fit")


async def test_the_derived_opening_fits_are_gone(database: Database) -> None:
    async with database.shared() as session:
        found = await session.execute(text("SELECT to_regclass('rolemap.posting_fit')"))
        assert found.scalar_one() is None


async def test_an_openings_fit_is_owner_zone_with_its_policy(database: Database) -> None:
    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT schemaname || '.' || tablename FROM pg_tables"
                " WHERE rowsecurity IS TRUE AND schemaname = 'target'"
            )
        )
        protected = set(rows.scalars())
        policies = await session.execute(
            text(
                "SELECT schemaname || '.' || tablename FROM pg_policies"
                " WHERE policyname = 'owner_isolation' AND schemaname = 'target'"
            )
        )
        with_policy = set(policies.scalars())
    assert set(_NEW) <= protected
    assert set(_NEW) <= with_policy
