"""What a build made of each candidate, against a real database (Phase 8):
kept per build, still readable after the candidate is replaced, and seen only
by its owner."""

from __future__ import annotations

import uuid

import pytest

from advisor.rolemap.domain import (
    BuildRun,
    CandidatePlacement,
    CandidatePlacementFilter,
    PlacementOutcome,
    RoleCandidate,
)
from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
from kernel.clock import utcnow
from kernel.db import Database

pytestmark = pytest.mark.integration


async def test_a_placement_outlives_its_candidate_and_only_its_owner_sees_it(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        build = await mine.builds.create(
            BuildRun.requested(owner_id=account, at=utcnow(), wait=False)
        )
        candidate = await mine.candidates.create(
            RoleCandidate(
                id=uuid.uuid4(),
                owner_id=account,
                assessment_id=uuid.uuid4(),
                rank=0,
                title="Data Engineer",
                description="Data pipelines.",
                dimension_keys=("data",),
            )
        )
        placement = await mine.placements.create(
            CandidatePlacement(
                id=uuid.uuid4(),
                owner_id=account,
                build_run_id=build.id,
                candidate_id=candidate.id,
                rank=0,
                title="Data Engineer",
                outcome=PlacementOutcome.OUTSIDE_TOP_K,
                opening_count=4,
                fit_estimate=0.12,
            )
        )

    async with uow.for_owner(account) as mine:
        [loaded] = await mine.placements.get_list(
            CandidatePlacementFilter(candidate_ids=(candidate.id,))
        )
        assert loaded == placement
        # The next analysis replaces the candidates: the record still reads.
        await mine.candidates.delete(candidate.id)

    async with uow.for_owner(account) as mine:
        [kept] = await mine.placements.get_list(CandidatePlacementFilter(build_run_id=build.id))
        assert (kept.candidate_id, kept.title, kept.outcome) == (
            None,
            "Data Engineer",
            PlacementOutcome.OUTSIDE_TOP_K,
        )

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.placements.get_count(CandidatePlacementFilter()) == 0
