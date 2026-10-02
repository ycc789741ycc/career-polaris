"""Postings of the user's own against a real database (Phase 8): what is
stored, that nobody else sees it, and that a Target is one shape or the other."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from advisor.gapplan.domain import GapPlan
from advisor.gapplan.infra.unit_of_work import SqlAlchemyGapPlanUnitOfWork
from advisor.rolemap.domain import (
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingFit,
    PostingFitBasis,
    PostingFitFilter,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    get_own_posting_key,
)
from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
from kernel.clock import utcnow
from kernel.db import Database

pytestmark = pytest.mark.integration


async def test_a_posting_of_your_own_round_trips_and_only_its_owner_sees_it(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    posting_id = uuid.uuid4()
    assessment_id = uuid.uuid4()
    requirement = {"statement": "Leads design", "weight": 0.9, "expected_level": "expert"}
    async with uow.for_owner(account) as mine:
        run = await mine.evaluations.create(
            PostingEvaluation.requested(
                owner_id=account,
                private_job_posting_id=posting_id,
                reads_requirements=True,
                at=utcnow(),
            )
        )
        await mine.posting_requirements.create(
            PostingRequirement(
                id=uuid.uuid4(),
                owner_id=account,
                private_job_posting_id=posting_id,
                statement="Leads design",
                weight=0.9,
                expected_level="expert",
            )
        )
        source = await mine.posting_requirement_fits.create(
            PostingRequirementFit(
                id=uuid.uuid4(),
                owner_id=account,
                private_job_posting_id=posting_id,
                assessment_id=assessment_id,
                requirements=(requirement,),
                requirement_map={"Leads design": "leadership"},
                target_profile={"leadership": 90},
                reasoning="Close.",
                model_id="claude-opus-5",
                template_version="v1",
            )
        )
        fit = await mine.posting_fits.create(
            PostingFit(
                id=uuid.uuid4(),
                owner_id=account,
                posting_key=get_own_posting_key(posting_id),
                basis=PostingFitBasis.OWN,
                source_fit_id=source.id,
                assessment_id=assessment_id,
                score=78,
                requirements=(requirement,),
                requirement_map={"Leads design": "leadership"},
                target_profile={"leadership": 90},
                gaps=(
                    {
                        "dimension_key": "leadership",
                        "user_score": 70,
                        "target_score": 90,
                        "delta": -20,
                    },
                ),
                uncovered=(),
            )
        )
        run.ready(utcnow())
        await mine.evaluations.update(run)

    async with uow.for_owner(account) as mine:
        [loaded_run] = await mine.evaluations.get_list(
            PostingEvaluationFilter(private_job_posting_id=posting_id)
        )
        assert (loaded_run.status, loaded_run.reads_requirements) == (run.status, True)
        [loaded_fit] = await mine.posting_fits.get_list(
            PostingFitFilter(posting_keys=(get_own_posting_key(posting_id),))
        )
        assert loaded_fit == fit
        assert (loaded_fit.basis, loaded_fit.source_fit_id) == (PostingFitBasis.OWN, source.id)
        assert await mine.posting_requirement_fits.get(source.id) == source
        assert (
            await mine.posting_requirements.get_count(
                PostingRequirementFilter(private_job_posting_id=posting_id)
            )
            == 1
        )

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.evaluations.get_count(PostingEvaluationFilter()) == 0
        assert await theirs.posting_requirements.get_count(PostingRequirementFilter()) == 0
        assert await theirs.posting_requirement_fits.get_count(PostingRequirementFitFilter()) == 0
        assert await theirs.posting_fits.get(fit.id) is None


@pytest.mark.parametrize("ids", ["neither", "both"])
async def test_a_plan_aims_at_a_role_or_a_posting_of_your_own_never_both_or_neither(
    database: Database, account: uuid.UUID, ids: str
) -> None:
    both = ids == "both"
    with pytest.raises(IntegrityError):
        async with SqlAlchemyGapPlanUnitOfWork(database).for_owner(account) as mine:
            await mine.plans.create(
                GapPlan.requested(
                    owner_id=account,
                    role_id=uuid.uuid4() if both else None,
                    job_posting_id=None,
                    private_job_posting_id=uuid.uuid4() if both else None,
                    label="Staff Engineer",
                    version=1,
                    at=utcnow(),
                )
            )
