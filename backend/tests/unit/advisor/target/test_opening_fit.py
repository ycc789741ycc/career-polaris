"""Scoring an opening against the user, with AI, when its gap analysis runs
(ADR 0073): read what its description asks for once, project that onto the
user's dimensions, and work the fit out locally. Against in-memory storage,
with the role map's fit kit and a role map that holds one role and opening."""

from __future__ import annotations

import uuid

import pytest

from advisor.market import PostingHeadView, Visibility
from advisor.rolemap import RoleMapService, RoleView
from advisor.target import TargetRef, TargetService
from advisor.target.domain import RequirementBasis
from kernel.errors import TargetUnusableError, ValidationError
from tests.unit.advisor.rolemap.fakes import FakeMarket, FakeRoleMapUnitOfWork
from tests.unit.advisor.target.fakes import FakeObjectStore, FakeTargetUnitOfWork
from tests.unit.advisor.target.test_service import (
    OWNER,
    NoAssessment,
    OwnPostingGateway,
    _with_strengths,
)

ROLE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
OPENING_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
REF = TargetRef(role_id=str(ROLE_ID), job_posting_id=str(OPENING_ID))

_ROLE = RoleView(
    id=ROLE_ID,
    name="Backend Engineer",
    hiring_bar=60,
    bar_basis="estimated",
    bar_confidence=0.5,
    bar_reasoning=None,
    opening_count=1,
    salary_bands={},
    requirements=(),
    is_coherent=True,
)
_OPENING = PostingHeadView(
    id=OPENING_ID,
    company_name="Acme",
    title="Senior Backend Engineer",
    location="Berlin",
    url=None,
    visibility=Visibility.SHARED,
    salary=None,
)


class MapWithOneOpening(RoleMapService):
    """The role map's fit kit, over a map holding one role with one opening,
    whose description is ``description`` (none: thinned)."""

    description: str | None = "We need Go services and on-call."

    async def roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        return [_ROLE]

    async def role_postings(
        self, owner_id: uuid.UUID
    ) -> list[tuple[RoleView, list[PostingHeadView]]]:
        return [(_ROLE, [_OPENING])]

    async def opening_description(self, job_posting_id: uuid.UUID) -> str | None:
        return self.description if job_posting_id == OPENING_ID else None


def _services(
    gateway: OwnPostingGateway | None = None,
) -> tuple[TargetService, MapWithOneOpening, FakeTargetUnitOfWork, OwnPostingGateway]:
    gateway = gateway or OwnPostingGateway()
    rolemap = MapWithOneOpening(
        FakeRoleMapUnitOfWork(),
        market=FakeMarket(),  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        embedding_model="test-model",
        top_k=10,
        candidate_count=20,
        ai_concurrency=4,
    )
    uow = FakeTargetUnitOfWork()
    target = TargetService(
        uow,
        assessment=NoAssessment(),  # type: ignore[arg-type]
        rolemap=rolemap,
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
        upload_max_bytes=1_000,
        upload_max_pages=2,
    )
    return target, rolemap, uow, gateway


class Checkpoints:
    def __init__(self) -> None:
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


async def test_an_unscored_opening_cannot_be_planned_against() -> None:
    target, rolemap, _uow, _gateway = _services()
    await _with_strengths(rolemap)

    assert not await target.is_scored(OWNER, REF)
    assert await target.get_opening_fit(OWNER, OPENING_ID) is None
    with pytest.raises(TargetUnusableError, match="run its gap analysis"):
        await target.snapshot(OWNER, REF)


async def test_scoring_an_opening_reads_its_description_then_projects_it() -> None:
    target, rolemap, uow, gateway = _services()
    await _with_strengths(rolemap)
    checkpoints = Checkpoints()

    await target.create_opening_fit(OWNER, REF, checkpoint=checkpoints)

    assert gateway.tasks == ["rolemap.extract", "rolemap.fit"]
    assert checkpoints.count == 2
    assert "Go services" in gateway.shown[0]["postings"]
    assert len(uow.store.opening_requirements) == 2
    snapshot = await target.snapshot(OWNER, REF)
    assert snapshot.basis is RequirementBasis.OPENING
    assert snapshot.label == "Backend Engineer · Acme"
    assert [r.statement for r in snapshot.requirements] == ["skill 0.9", "skill 0.4"]
    # skill 0.4 maps onto nothing the user has: uncovered.
    assert [u.statement for u in snapshot.uncovered] == ["skill 0.4"]
    found = await target.get_opening_fit(OWNER, OPENING_ID)
    assert found is not None and found.fit == snapshot.fit_score and not found.is_stale


async def test_a_current_opening_fit_is_not_scored_again() -> None:
    target, rolemap, _uow, gateway = _services()
    await _with_strengths(rolemap)
    await target.create_opening_fit(OWNER, REF, checkpoint=Checkpoints())

    await target.create_opening_fit(OWNER, REF, checkpoint=Checkpoints())

    assert gateway.tasks == ["rolemap.extract", "rolemap.fit"]
    assert await target.is_scored(OWNER, REF)
    priced = await target.estimate_opening_fit(OWNER, REF)
    assert priced["cost_usd"] == "0"


async def test_after_a_new_analysis_an_opening_is_rescored_without_reading_it_again() -> None:
    target, rolemap, uow, gateway = _services()
    await _with_strengths(rolemap)
    await target.create_opening_fit(OWNER, REF, checkpoint=Checkpoints())
    await _with_strengths(rolemap, backend=90)

    assert not await target.is_scored(OWNER, REF)
    found = await target.get_opening_fit(OWNER, OPENING_ID)
    assert found is not None and found.is_stale
    await target.create_opening_fit(OWNER, REF, checkpoint=Checkpoints())

    assert gateway.tasks == ["rolemap.extract", "rolemap.fit", "rolemap.fit"]
    assert len(uow.store.opening_requirements) == 2
    assert await target.is_scored(OWNER, REF)


async def test_scoring_an_opening_is_priced_at_reading_and_projecting_it() -> None:
    target, rolemap, _uow, _gateway = _services()
    await _with_strengths(rolemap)

    priced = await target.estimate_opening_fit(OWNER, REF)

    # One estimate to read it, one to project it, at 0.10 each.
    assert priced["cost_usd"] == "0.20"


async def test_an_opening_whose_description_is_gone_cannot_be_scored() -> None:
    target, rolemap, _uow, gateway = _services()
    await _with_strengths(rolemap)
    rolemap.description = None

    with pytest.raises(ValidationError, match="no longer available"):
        await target.create_opening_fit(OWNER, REF, checkpoint=Checkpoints())

    assert gateway.tasks == []


async def test_a_checkpoint_that_raises_stops_before_the_call() -> None:
    target, rolemap, _uow, gateway = _services()
    await _with_strengths(rolemap)

    class StoppedError(Exception):
        pass

    async def stop() -> None:
        raise StoppedError

    with pytest.raises(StoppedError):
        await target.create_opening_fit(OWNER, REF, checkpoint=stop)

    assert gateway.tasks == []


async def test_a_role_and_an_own_posting_count_as_scored() -> None:
    target, _rolemap, _uow, _gateway = _services()

    assert await target.is_scored(OWNER, TargetRef(role_id=str(ROLE_ID)))
    assert await target.is_scored(OWNER, TargetRef(private_job_posting_id=str(uuid.uuid4())))


async def test_an_opening_is_labelled_by_its_role_and_company_before_it_is_scored() -> None:
    target, _rolemap, _uow, _gateway = _services()

    assert await target.get_label(OWNER, REF) == "Backend Engineer · Acme"
