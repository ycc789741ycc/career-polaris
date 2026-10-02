"""Postings of the user's own against a real database (Phase 8, ADR 0033):
what Target stores, that nobody else sees it, that removing a posting takes
everything made of it, and that a Target is one shape or the other."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from advisor.gapplan.domain import GapPlan
from advisor.gapplan.infra.unit_of_work import SqlAlchemyGapPlanUnitOfWork
from advisor.target.domain import (
    OwnPostingFit,
    OwnPostingFitFilter,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    PrivateJobPosting,
    PrivateJobPostingFilter,
)
from advisor.target.infra.unit_of_work import SqlAlchemyTargetUnitOfWork
from kernel.clock import utcnow
from kernel.db import Database

pytestmark = pytest.mark.integration

_REQUIREMENT = {"statement": "Leads design", "weight": 0.9, "expected_level": "expert"}


async def _scored(uow: SqlAlchemyTargetUnitOfWork, owner_id: uuid.UUID) -> OwnPostingFit:
    """A posting of the user's own, read and scored once."""
    assessment_id = uuid.uuid4()
    async with uow.for_owner(owner_id) as mine:
        posting = await mine.postings.create(
            PrivateJobPosting.added(
                owner_id=owner_id,
                title="Staff Engineer",
                company_name=None,
                job_description="Lead design across three teams.",
            )
        )
        run = await mine.evaluations.create(
            PostingEvaluation.requested(
                owner_id=owner_id,
                private_job_posting_id=posting.id,
                reads_requirements=True,
                at=utcnow(),
            )
        )
        await mine.requirements.create(
            PostingRequirement(
                id=uuid.uuid4(),
                owner_id=owner_id,
                private_job_posting_id=posting.id,
                statement="Leads design",
                weight=0.9,
                expected_level="expert",
            )
        )
        source = await mine.requirement_fits.create(
            PostingRequirementFit(
                id=uuid.uuid4(),
                owner_id=owner_id,
                private_job_posting_id=posting.id,
                assessment_id=assessment_id,
                requirements=(_REQUIREMENT,),
                requirement_map={"Leads design": "leadership"},
                target_profile={"leadership": 90},
                reasoning="Close.",
                model_id="claude-opus-5",
                template_version="v1",
                requirements_digest="d" * 64,
            )
        )
        fit = await mine.fits.create(
            OwnPostingFit(
                id=uuid.uuid4(),
                owner_id=owner_id,
                private_job_posting_id=posting.id,
                source_fit_id=source.id,
                assessment_id=assessment_id,
                score=78,
                requirements=(_REQUIREMENT,),
                requirement_map={"Leads design": "leadership"},
                target_profile={"leadership": 90},
                gaps=(
                    {
                        "dimension_key": "leadership",
                        "user_score": 70,
                        "target_score": 90,
                        "delta": -20,
                        "weight": 1.0,
                    },
                ),
                uncovered=(),
            )
        )
        run.ready(utcnow())
        await mine.evaluations.update(run)
    return fit


async def test_a_posting_of_your_own_round_trips_and_only_its_owner_sees_it(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyTargetUnitOfWork(database)
    fit = await _scored(uow, account)
    posting_id = fit.private_job_posting_id

    async with uow.for_owner(account) as mine:
        posting = await mine.postings.get(posting_id)
        assert posting is not None
        assert (posting.title, posting.company_name) == ("Staff Engineer", None)
        [loaded_run] = await mine.evaluations.get_list(
            PostingEvaluationFilter(private_job_posting_id=posting_id)
        )
        assert (str(loaded_run.status), loaded_run.reads_requirements) == ("ready", True)
        [loaded_fit] = await mine.fits.get_list(
            OwnPostingFitFilter(private_job_posting_ids=(posting_id,))
        )
        assert loaded_fit == fit
        source = await mine.requirement_fits.get(fit.source_fit_id)
        assert source is not None and source.requirements_digest == "d" * 64
        assert (
            await mine.requirements.get_count(
                PostingRequirementFilter(private_job_posting_id=posting_id)
            )
            == 1
        )

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.postings.get_count(PrivateJobPostingFilter()) == 0
        assert await theirs.evaluations.get_count(PostingEvaluationFilter()) == 0
        assert await theirs.requirements.get_count(PostingRequirementFilter()) == 0
        assert await theirs.requirement_fits.get_count(PostingRequirementFitFilter()) == 0
        assert await theirs.fits.get(fit.id) is None


async def test_removing_a_posting_of_your_own_takes_what_was_made_of_it(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyTargetUnitOfWork(database)
    fit = await _scored(uow, account)

    async with uow.for_owner(account) as mine:
        await mine.postings.delete(fit.private_job_posting_id)

    async with uow.for_owner(account) as mine:
        assert await mine.evaluations.get_count(PostingEvaluationFilter()) == 0
        assert await mine.requirements.get_count(PostingRequirementFilter()) == 0
        assert await mine.requirement_fits.get_count(PostingRequirementFitFilter()) == 0
        assert await mine.fits.get_count(OwnPostingFitFilter()) == 0


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
