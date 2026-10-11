"""Migration 0054: a finished build learns the analysis it built from, through
the candidates it placed (ADR 0070). The backfill runs here as each owner,
under the owner policy."""

from __future__ import annotations

import importlib
import uuid

import pytest
from sqlalchemy import text

from kernel.db import Database

pytestmark = pytest.mark.integration

BACKFILL = importlib.import_module(
    "migrations.versions.20261025_0054_build_skill_assessment"
).BACKFILL_SKILL_ASSESSMENTS


async def _build(database: Database, owner: uuid.UUID, *, status: str) -> uuid.UUID:
    build_id = uuid.uuid4()
    async with database.for_user(owner) as session:
        await session.execute(
            text(
                "INSERT INTO rolemap.build_run (id, owner_id, status, requested_at)"
                " VALUES (:id, :owner, :status, now())"
            ),
            {"id": build_id, "owner": owner, "status": status},
        )
    return build_id


async def _placed(
    database: Database, owner: uuid.UUID, build_id: uuid.UUID, analysis_id: uuid.UUID
) -> uuid.UUID:
    candidate_id = uuid.uuid4()
    async with database.for_user(owner) as session:
        await session.execute(
            text(
                "INSERT INTO rolemap.role_candidate"
                " (id, owner_id, assessment_id, rank, title, description, dimension_keys)"
                " VALUES (:id, :owner, :analysis, 0, 'Backend Engineer', 'x', '[]')"
            ),
            {"id": candidate_id, "owner": owner, "analysis": analysis_id},
        )
        await session.execute(
            text(
                "INSERT INTO rolemap.candidate_placement (id, owner_id, build_run_id,"
                " candidate_id, rank, title, outcome, opening_count)"
                " VALUES (:id, :owner, :build, :candidate, 0, 'Backend Engineer',"
                " 'too_few_openings', 0)"
            ),
            {"id": uuid.uuid4(), "owner": owner, "build": build_id, "candidate": candidate_id},
        )
    return candidate_id


async def _recorded(database: Database, owner: uuid.UUID, build_id: uuid.UUID) -> object:
    async with database.for_user(owner) as session:
        await session.execute(text(BACKFILL))
    async with database.for_user(owner) as session:
        return (
            await session.execute(
                text("SELECT skill_assessment_id FROM rolemap.build_run WHERE id = :id"),
                {"id": build_id},
            )
        ).scalar_one()


async def test_a_finished_build_records_the_analysis_its_candidates_came_from(
    database: Database, account: uuid.UUID
) -> None:
    analysis_id = uuid.uuid4()
    build_id = await _build(database, account, status="ready")
    await _placed(database, account, build_id, analysis_id)

    assert await _recorded(database, account, build_id) == analysis_id
    # Run again, it changes nothing.
    assert await _recorded(database, account, build_id) == analysis_id


async def test_a_build_whose_candidates_are_gone_or_that_failed_keeps_a_null(
    database: Database, account: uuid.UUID
) -> None:
    replaced = await _build(database, account, status="ready")
    candidate_id = await _placed(database, account, replaced, uuid.uuid4())
    async with database.for_user(account) as session:
        await session.execute(
            text("DELETE FROM rolemap.role_candidate WHERE id = :id"), {"id": candidate_id}
        )
    failed = await _build(database, account, status="failed")
    await _placed(database, account, failed, uuid.uuid4())

    assert await _recorded(database, account, replaced) is None
    assert await _recorded(database, account, failed) is None
