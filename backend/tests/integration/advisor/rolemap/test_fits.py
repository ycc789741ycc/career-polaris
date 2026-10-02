"""The fit in the role map, against a real database (ADR 0028): a fit snapshot
and the scores it is taken against survive their mappers, nobody else sees
them, and scoring is announced the way the dispatcher reads it."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from advisor.rolemap.domain import (
    CandidateStrength,
    CandidateStrengthFilter,
    RoleFit,
    RoleFitFilter,
    RoleFitsComputed,
)
from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration


async def test_a_fit_round_trips_and_is_its_owners_alone(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    role_id = uuid.uuid4()
    async with uow.for_owner(account) as mine:
        fit = await mine.fits.create(
            RoleFit(
                id=uuid.uuid4(),
                owner_id=account,
                assessment_id=uuid.uuid4(),
                role_id=role_id,
                score=64,
                reasoning="close",
                target_profile={"api": 80},
                gaps=({"dimension_key": "api", "user_score": 72, "target_score": 80, "delta": -8},),
                uncovered=({"statement": "Kafka", "weight": 0.5},),
                model_id="m",
                template_version="v1",
                requirements=({"statement": "APIs", "weight": 0.9, "expected_level": "expert"},),
                requirement_map={"APIs": "api"},
            )
        )
    assert fit.created_at is not None

    async with uow.for_owner(account) as mine:
        assert await mine.fits.get_list(RoleFitFilter(role_id=role_id)) == [fit]
        assert await mine.fits.get_list(RoleFitFilter(role_id=uuid.uuid4())) == []

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.fits.get(fit.id) is None
        assert await theirs.fits.get_count(RoleFitFilter()) == 0


async def test_a_strength_keeps_the_score_and_confidence_its_weight_came_from(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        stored = await mine.strengths.create(
            CandidateStrength(
                id=uuid.uuid4(),
                owner_id=account,
                assessment_id=uuid.uuid4(),
                dimension_key="api",
                name="API design",
                read="Designed the public API.",
                weight=0.54,
                score=60,
                confidence=0.9,
            )
        )

    async with uow.for_owner(account) as mine:
        assert await mine.strengths.get_list(CandidateStrengthFilter()) == [stored]


async def test_scoring_the_fits_reaches_the_outbox(database: Database, account: uuid.UUID) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        mine.record(RoleFitsComputed(owner_id=account, roles=3))

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert [tuple(row) for row in rows.all()] == [("RoleFitsComputed", {"roles": 3})]
