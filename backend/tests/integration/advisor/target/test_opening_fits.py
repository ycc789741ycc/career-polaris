"""An opening's fit against a real database (ADR 0073): what its gap analysis
stores in Target, that it round-trips, and that nobody else sees it."""

from __future__ import annotations

import uuid

import pytest

from advisor.target.domain import (
    OpeningFit,
    OpeningFitFilter,
    OpeningRequirement,
    OpeningRequirementFilter,
    OpeningRequirementFit,
    OpeningRequirementFitFilter,
)
from advisor.target.infra.unit_of_work import SqlAlchemyTargetUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration

_REQUIREMENT = {"statement": "Go services", "weight": 0.9, "expected_level": "senior"}


async def _scored(uow: SqlAlchemyTargetUnitOfWork, owner_id: uuid.UUID) -> OpeningFit:
    """One opening, read and scored once. Its id names a shared posting no
    longer anywhere: what was read of it outlives it."""
    job_posting_id = uuid.uuid4()
    assessment_id = uuid.uuid4()
    async with uow.for_owner(owner_id) as mine:
        await mine.opening_requirements.create(
            OpeningRequirement(
                id=uuid.uuid4(),
                owner_id=owner_id,
                job_posting_id=job_posting_id,
                statement="Go services",
                weight=0.9,
                expected_level="senior",
            )
        )
        source = await mine.opening_requirement_fits.create(
            OpeningRequirementFit(
                id=uuid.uuid4(),
                owner_id=owner_id,
                job_posting_id=job_posting_id,
                assessment_id=assessment_id,
                requirements=(_REQUIREMENT,),
                requirement_map={"Go services": "backend"},
                target_profile={"backend": 80},
                reasoning="Close on services.",
                model_id="claude-opus-5",
                template_version="role_fit@v1",
                requirements_digest="d" * 64,
            )
        )
        return await mine.opening_fits.create(
            OpeningFit(
                id=uuid.uuid4(),
                owner_id=owner_id,
                job_posting_id=job_posting_id,
                source_fit_id=source.id,
                assessment_id=assessment_id,
                score=72,
                requirements=(_REQUIREMENT,),
                requirement_map={"Go services": "backend"},
                target_profile={"backend": 80},
                gaps=({"dimension_key": "backend", "user_score": 60, "target_score": 80},),
                uncovered=(),
            )
        )


async def test_an_openings_fit_round_trips_and_only_its_owner_sees_it(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyTargetUnitOfWork(database)
    fit = await _scored(uow, account)
    opening = fit.job_posting_id

    async with uow.for_owner(account) as mine:
        [loaded] = await mine.opening_fits.get_list(OpeningFitFilter(job_posting_ids=(opening,)))
        assert loaded == fit
        source = await mine.opening_requirement_fits.get(fit.source_fit_id)
        assert source is not None and source.requirements_digest == "d" * 64
        [read] = await mine.opening_requirements.get_list(
            OpeningRequirementFilter(job_posting_id=opening)
        )
        assert (read.statement, read.weight) == ("Go services", 0.9)

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.opening_fits.get_count(OpeningFitFilter()) == 0
        assert await theirs.opening_requirement_fits.get_count(OpeningRequirementFitFilter()) == 0
        assert await theirs.opening_requirements.get_count(OpeningRequirementFilter()) == 0


async def test_the_newest_fit_of_an_opening_is_its_current_one(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyTargetUnitOfWork(database)
    first = await _scored(uow, account)
    async with uow.for_owner(account) as mine:
        newer = await mine.opening_fits.create(
            OpeningFit(
                id=uuid.uuid4(),
                owner_id=account,
                job_posting_id=first.job_posting_id,
                source_fit_id=first.source_fit_id,
                assessment_id=uuid.uuid4(),
                score=88,
                requirements=first.requirements,
                requirement_map=first.requirement_map,
                target_profile=first.target_profile,
                gaps=(),
                uncovered=(),
            )
        )
        [current] = await mine.opening_fits.get_list(
            OpeningFitFilter(job_posting_ids=(first.job_posting_id,)), page_size=1
        )

    assert current.id == newer.id
