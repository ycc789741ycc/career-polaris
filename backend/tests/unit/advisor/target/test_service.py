"""Target's use cases for postings of the user's own, against in-memory
storage: what they store, with no database and no model. The fit is scored
with the role map's fit kit, over the role map's own in-memory storage."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from advisor.rolemap import RoleMapService, StrengthInput
from advisor.rolemap.service import _Projection, _RoleExtraction
from advisor.target import TargetRef, TargetService
from advisor.target.domain import RequirementBasis
from kernel.errors import BudgetExceededError, NotFoundError, ValidationError
from tests.unit.advisor.rolemap.fakes import FakeMarket, FakeRoleMapUnitOfWork
from tests.unit.advisor.target.fakes import FakeTargetUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Reply:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.model_id = "claude-opus-5"
        self.template_version = "v1"


class _Estimated:
    cost_usd = Decimal("0.10")
    model_id = "claude-opus-5"
    rate_is_published = True


class OwnPostingGateway:
    """Reads a JD's requirements, then maps them: ``skill 0.9`` onto
    ``backend``, wanted at ``target``, and ``skill 0.4`` onto nothing the user
    has. Records each call's task. ``fails`` makes the named task fail."""

    def __init__(self, target: int = 80, *, fails: str | None = None) -> None:
        self.target = target
        self.fails = fails
        self.tasks: list[str] = []
        self.shown: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, task: str, inputs: dict[str, str], **_: Any):
        self.tasks.append(task)
        self.shown.append(inputs)
        if task == self.fails:
            raise BudgetExceededError("over the monthly budget")
        if task == "rolemap.extract":
            return _Reply(
                _RoleExtraction.model_validate(
                    {
                        "name": "Whatever the model calls it",
                        "requirements": [
                            {"statement": f"skill {w}", "weight": w, "expected_level": "senior"}
                            for w in (0.4, 0.9)
                        ],
                    }
                )
            )
        return _Reply(
            _Projection.model_validate(
                {
                    "mappings": [
                        {"requirement_statement": "skill 0.9", "dimension_id": "backend"},
                        {"requirement_statement": "skill 0.4", "dimension_id": "nowhere"},
                    ],
                    "target_scores": [{"dimension_id": "backend", "target": self.target}],
                    "reasoning": "Close on services.",
                }
            )
        )

    async def estimate(self, owner_id: uuid.UUID, **_: Any) -> _Estimated:
        return _Estimated()


class NoAssessment:
    """The analysis's dimension names: none, so a snapshot keeps the keys."""

    async def latest(self, owner_id: uuid.UUID) -> None:
        return None


def _services(
    gateway: Any = None,
) -> tuple[TargetService, RoleMapService, FakeTargetUnitOfWork, FakeRoleMapUnitOfWork]:
    rolemap_uow = FakeRoleMapUnitOfWork()
    if gateway is None:
        gateway = OwnPostingGateway()
    rolemap = RoleMapService(
        rolemap_uow,
        market=FakeMarket(),  # type: ignore[arg-type]
        gateway=gateway,
        embedding_model="test-model",
        top_k=10,
        candidate_count=20,
    )
    uow = FakeTargetUnitOfWork()
    target = TargetService(uow, assessment=NoAssessment(), rolemap=rolemap)  # type: ignore[arg-type]
    return target, rolemap, uow, rolemap_uow


async def _with_strengths(rolemap: RoleMapService, *, backend: int = 60) -> uuid.UUID:
    assessment_id = uuid.uuid4()
    await rolemap.replace_candidates(
        OWNER,
        assessment_id,
        [],
        strengths=[StrengthInput("backend", "Backend", "Built services.", backend, 0.9)],
    )
    return assessment_id


async def _add_own(target: TargetService) -> tuple[uuid.UUID, uuid.UUID]:
    posting, run_id = await target.add_own_posting(
        OWNER,
        title=" Staff Engineer ",
        company_name=" Northwind ",
        job_description="Own the ledger. Lead incident response.",
    )
    return posting.private_job_posting_id, run_id


async def test_a_posting_of_your_own_is_stored_privately_and_waits_to_be_scored() -> None:
    target, rolemap, uow, rolemap_uow = _services()
    await _with_strengths(rolemap)

    posting, _run_id = await target.add_own_posting(
        OWNER, title=" Staff Engineer ", company_name=" Northwind ", job_description=" Own it. "
    )

    assert (posting.title, posting.company_name, posting.status) == (
        "Staff Engineer",
        "Northwind",
        "running",
    )
    assert posting.fit is None
    assert uow.store.postings[posting.private_job_posting_id].job_description == "Own it."
    # Never on the map, and nothing built.
    assert await rolemap.roles(OWNER) == [] and rolemap_uow.store.builds == {}


@pytest.mark.parametrize(
    ("title", "description"),
    [("  ", "Own it."), ("Staff Engineer", "   "), ("x" * 256, "Own it.")],
)
async def test_a_posting_of_your_own_needs_a_title_and_its_jd(title: str, description: str) -> None:
    target, rolemap, uow, _ = _services()
    await _with_strengths(rolemap)

    with pytest.raises(ValidationError):
        await target.add_own_posting(
            OWNER, title=title, company_name=None, job_description=description
        )
    assert uow.store.postings == {}


async def test_a_posting_of_your_own_needs_an_analysis_first() -> None:
    target, _rolemap, uow, _ = _services()

    with pytest.raises(ValidationError):
        await _add_own(target)
    assert uow.store.postings == {}


async def test_scoring_a_posting_reads_its_jd_then_works_its_fit_out_locally() -> None:
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway)
    assessment_id = await _with_strengths(rolemap)
    _posting_id, run_id = await _add_own(target)

    await target.evaluate_own_posting(OWNER, run_id)

    # Two calls, the JD read once and then projected.
    assert gateway.tasks == ["rolemap.extract", "rolemap.fit"]
    assert "Own the ledger" in gateway.shown[0]["postings"]
    assert [r.statement for r in uow.store.requirements.values()] == ["skill 0.9", "skill 0.4"]
    [source] = uow.store.requirement_fits.values()
    assert source.target_profile == {"backend": 80}
    assert source.requirement_map == {"skill 0.9": "backend", "skill 0.4": None}
    [fit] = uow.store.fits.values()
    assert fit.source_fit_id == source.id and fit.assessment_id == assessment_id
    assert [(g["dimension_key"], g["delta"]) for g in fit.gaps] == [("backend", -20)]
    assert [u["statement"] for u in fit.uncovered] == ["skill 0.4"]
    [listed] = await target.own_postings(OWNER)
    assert (listed.status, listed.fit, listed.is_stale) == ("ready", fit.score, False)


async def test_a_posting_fit_is_never_an_ai_call() -> None:
    """Worked out from the AI fit with a gateway that refuses every call."""

    class NoCalls:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a posting fit made an AI call")

    target, rolemap, uow, rolemap_uow = _services(OwnPostingGateway(target=80))
    await _with_strengths(rolemap)
    _posting_id, run_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, run_id)
    [source] = uow.store.requirement_fits.values()

    local_rolemap = RoleMapService(
        rolemap_uow,
        market=FakeMarket(),  # type: ignore[arg-type]
        gateway=NoCalls(),  # type: ignore[arg-type]
        embedding_model="test-model",
        top_k=10,
        candidate_count=20,
    )
    local = TargetService(uow, assessment=NoAssessment(), rolemap=local_rolemap)  # type: ignore[arg-type]
    strengths = await local_rolemap.strengths(OWNER)
    assert strengths is not None
    await local._create_fit(OWNER, strengths, source)

    fits = sorted(uow.store.fits.values(), key=lambda f: str(f.created_at))
    assert len(fits) == 2 and fits[0].score == fits[1].score
    assert all(f.source_fit_id == source.id for f in fits)


async def test_a_failed_read_is_recorded_on_the_run_not_raised() -> None:
    target, rolemap, uow, _ = _services(OwnPostingGateway(fails="rolemap.fit"))
    await _with_strengths(rolemap)
    posting_id, run_id = await _add_own(target)

    await target.evaluate_own_posting(OWNER, run_id)

    [listed] = await target.own_postings(OWNER)
    assert listed.status == "failed" and listed.error_code == "ai_budget_exceeded"
    assert listed.fit is None and uow.store.fits == {}
    with pytest.raises(Exception, match="not been scored"):
        await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))


async def test_a_rescore_keeps_the_requirements_and_spends_one_call() -> None:
    gateway = OwnPostingGateway(target=80)
    target, rolemap, _uow, _ = _services(gateway)
    await _with_strengths(rolemap, backend=60)
    posting_id, run_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, run_id)
    # A new analysis: the fit was scored against earlier strengths.
    await _with_strengths(rolemap, backend=80)
    [stale] = await target.own_postings(OWNER)
    assert stale.is_stale
    gateway.tasks.clear()

    _posting, rescore_id = await target.rescore_own_posting(OWNER, posting_id)
    assert rescore_id is not None
    await target.evaluate_own_posting(OWNER, rescore_id)

    assert gateway.tasks == ["rolemap.fit"]
    snapshot = await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))
    assert [(d.dimension_key, d.user_score) for d in snapshot.dimensions] == [("backend", 80)]
    [fresh] = await target.own_postings(OWNER)
    assert not fresh.is_stale


async def test_rescoring_a_posting_against_unchanged_scores_makes_no_call() -> None:
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway)
    await _with_strengths(rolemap)
    posting_id, run_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, run_id)
    gateway.tasks.clear()

    _posting, rescore_id = await target.rescore_own_posting(OWNER, posting_id)
    assert rescore_id is not None
    await target.evaluate_own_posting(OWNER, rescore_id)

    assert gateway.tasks == []
    assert len(uow.store.requirement_fits) == 1
    [listed] = await target.own_postings(OWNER)
    assert listed.status == "ready" and listed.fit is not None


async def test_a_rescore_asked_for_while_one_runs_joins_it() -> None:
    target, rolemap, _uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id, _run_id = await _add_own(target)

    posting, run_id = await target.rescore_own_posting(OWNER, posting_id)

    assert run_id is None and posting.status == "running"


async def test_adding_a_posting_of_your_own_is_priced_at_two_calls() -> None:
    target, _rolemap, _uow, _ = _services()

    priced = await target.estimate_own_posting(
        OWNER, title="Staff Engineer", company_name=None, job_description="Own it."
    )

    assert priced == {"cost_usd": "0.20", "model_id": "claude-opus-5", "rate_is_published": True}


async def test_rescoring_a_posting_of_your_own_is_priced_at_one_call() -> None:
    target, rolemap, _uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id, _run_id = await _add_own(target)

    priced = await target.estimate_rescore(OWNER, posting_id)

    assert priced["cost_usd"] == "0.10"


async def test_a_snapshot_of_a_posting_of_your_own_is_planned_against_its_jd() -> None:
    target, rolemap, _uow, _ = _services(OwnPostingGateway(target=80))
    await _with_strengths(rolemap)
    posting_id, run_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, run_id)

    snapshot = await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))

    assert (snapshot.title, snapshot.company, snapshot.role_id) == (
        "Staff Engineer",
        "Northwind",
        None,
    )
    assert snapshot.basis is RequirementBasis.POSTING
    assert [r.statement for r in snapshot.requirements] == ["skill 0.9", "skill 0.4"]
    assert [u.statement for u in snapshot.uncovered] == ["skill 0.4"]


async def test_removing_a_posting_of_your_own_deletes_it_and_its_fit() -> None:
    target, rolemap, uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id, run_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, run_id)

    await target.remove_own_posting(OWNER, posting_id)

    assert await target.own_postings(OWNER) == []
    assert not (
        uow.store.postings
        or uow.store.evaluations
        or uow.store.requirements
        or uow.store.requirement_fits
        or uow.store.fits
    )
    with pytest.raises(NotFoundError):
        await target.remove_own_posting(OWNER, posting_id)


async def test_another_users_posting_is_not_found() -> None:
    target, rolemap, _uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id, _run_id = await _add_own(target)

    assert await target.own_postings(OTHER) == []
    with pytest.raises(NotFoundError):
        await target.own_posting(OTHER, posting_id)
    with pytest.raises(NotFoundError):
        await target.snapshot(OTHER, TargetRef(private_job_posting_id=str(posting_id)))
