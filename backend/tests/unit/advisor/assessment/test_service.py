"""Assessment use cases against in-memory storage: what they store and announce,
with no database and no model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from advisor.assessment import AssessmentService
from advisor.assessment.domain import (
    AnalysisFinished,
    AssessmentCompleted,
    DimensionsChanged,
    DimensionScore,
    LineageKind,
)
from kernel.errors import (
    BudgetExceededError,
    NotFoundError,
    OutputInvalidError,
)
from tests.unit.advisor.assessment.fakes import FakeAssessmentUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


@dataclass(frozen=True)
class _Evidence:
    id: str
    source: str
    reference: str
    fact: str


@dataclass(frozen=True)
class _Snapshot:
    evidence: tuple[_Evidence, ...]
    positions: tuple[Any, ...] = ()
    version: int = 1


class FakeProfile:
    def __init__(self, version: int = 1) -> None:
        self.current_version = version

    async def version(self, owner_id: uuid.UUID) -> int:
        return self.current_version

    async def snapshot(self, owner_id: uuid.UUID) -> _Snapshot:
        return _Snapshot(evidence=(_Evidence("e1", "github", "GitHub · api", "12 merged PRs"),))

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        return {"e1"}


@dataclass
class _Result:
    value: Any
    model_id: str = "model"
    template_version: str = "v1"


class FakeGateway:
    """Answers with a canned reply, or fails the way the real gateway can."""

    def __init__(self, reply: dict[str, Any] | None = None, error: Exception | None = None):
        self.reply = reply or {}
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, inputs: dict[str, str], **kwargs: Any) -> _Result:
        self.calls.append(inputs)
        if self.error is not None:
            raise self.error
        return _Result(value=kwargs["output_schema"].model_validate(self.reply))


def _service(
    uow: FakeAssessmentUnitOfWork,
    profile: FakeProfile | None = None,
    gateway: FakeGateway | None = None,
) -> AssessmentService:
    return AssessmentService(
        uow,
        profile=profile or FakeProfile(),  # type: ignore[arg-type]
        rolemap=None,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        confidence_threshold=0.5,
    )


def _dimension(key: str, name: str, score: int = 60, confidence: float = 0.8) -> DimensionScore:
    return DimensionScore(
        dimension_id=key,
        name=name,
        short_name=name[:8],
        score=score,
        confidence=confidence,
        read=f"{name} read",
        evidence_ids=("e1",),
    )


async def _assess(
    service: AssessmentService, dimensions: list[DimensionScore], version: int = 1
) -> uuid.UUID:
    existing = await service._existing_dimensions(OWNER)
    return await service._store(
        OWNER,
        snapshot_version=version,
        dimensions=dimensions,
        existing=existing,
        model_id="model",
        template_version="v1",
    )


async def test_an_assessment_is_stored_as_a_snapshot_and_announced() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)

    assessment_id = await _assess(service, [_dimension("api", "APIs"), _dimension("db", "Data")])

    latest = await service.latest(OWNER)
    assert latest is not None and latest.id == assessment_id
    assert [d.key for d in latest.dimensions] == ["api", "db"]
    assert latest.dimensions[0].name == "APIs" and latest.profile_version == 1
    assert uow.store.events == [
        AssessmentCompleted(
            owner_id=OWNER, assessment_id=assessment_id, dimensions=2, model_id="model"
        ),
        DimensionsChanged(owner_id=OWNER, added_or_renamed=2, retired=0),
    ]
    assert await service.latest(OTHER) is None


async def test_an_assessment_is_up_to_date_while_the_profile_has_not_changed() -> None:
    service = _service(FakeAssessmentUnitOfWork(), FakeProfile(version=3))
    await _assess(service, [_dimension("api", "APIs")], version=3)

    latest = await service.latest(OWNER)
    assert latest is not None and latest.is_out_of_date is False


async def test_any_change_to_the_profile_puts_every_earlier_assessment_out_of_date() -> None:
    profile = FakeProfile(version=1)
    service = _service(FakeAssessmentUnitOfWork(), profile)
    await _assess(service, [_dimension("api", "APIs")], version=1)
    await _assess(service, [_dimension("api", "APIs")], version=2)
    profile.current_version = 2

    history = (await service.history(OWNER)).items
    assert [(h.profile_version, h.is_out_of_date) for h in history] == [(2, False), (1, True)]

    # A sync, an upload, a disconnect or a deleted résumé: each bumps it.
    profile.current_version = 3
    latest = await service.latest(OWNER)
    assert latest is not None and latest.is_out_of_date is True


async def test_a_score_below_the_threshold_says_it_needs_more_evidence() -> None:
    # Strengths points to Sources for a score like this; it asks nothing.
    service = _service(FakeAssessmentUnitOfWork())
    await _assess(
        service,
        [_dimension("api", "APIs", confidence=0.8), _dimension("db", "Data", confidence=0.4)],
    )

    latest = await service.latest(OWNER)
    assert latest is not None
    assert {d.key: d.needs_more_evidence for d in latest.dimensions} == {
        "api": False,
        "db": True,
    }
    history = (await service.history(OWNER)).items
    assert [d.needs_more_evidence for d in history[0].dimensions] == [False, True]
    # The report carries how sure it is overall, so no screen averages it.
    assert latest.profile_confidence == pytest.approx(0.6)


async def test_a_dimension_that_disappears_is_retired_with_a_record() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)
    await _assess(service, [_dimension("api", "APIs"), _dimension("db", "Data")])

    second = await _assess(service, [_dimension("api", "API design")], version=2)

    dimensions = {d.key: d for d in uow.store.dimensions.values()}
    assert dimensions["db"].retired_at is not None
    assert dimensions["api"].name == "API design" and dimensions["api"].retired_at is None
    merged = [c for c in uow.store.changes.values() if c.assessment_id == second]
    assert any(c.kind is LineageKind.MERGED and c.dimension_key == "db" for c in merged)
    history = (await service.history(OWNER)).items
    assert [h.profile_version for h in history] == [2, 1]


async def test_history_is_paged_by_the_store_and_counts_every_run() -> None:
    service = _service(FakeAssessmentUnitOfWork())
    for version in (1, 2, 3):
        await _assess(service, [_dimension("api", "APIs")], version=version)

    page = await service.history(OWNER, page=2, page_size=2)

    assert (page.page, page.page_size, page.total) == (2, 2, 3)
    assert [a.profile_version for a in page.items] == [1]


# --- analysis runs (ADR 0006, ADR 0018) ------------------------------------


async def test_a_requested_analysis_is_running_before_its_job_starts() -> None:
    service = _service(FakeAssessmentUnitOfWork())

    requested = await service.request_run(OWNER)

    latest = await service.latest_run(OWNER)
    assert latest == requested and latest.is_running
    assert await service.latest_run(OTHER) is None


async def test_a_finished_analysis_closes_its_run_and_announces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)
    requested = await service.request_run(OWNER)
    produced = object()

    async def run(owner_id: uuid.UUID) -> object:
        return produced

    monkeypatch.setattr(service, "run", run)

    assert await service.analyse(OWNER, requested.id) is produced

    latest = await service.latest_run(OWNER)
    assert latest is not None and latest.status == "ready" and latest.finished_at is not None
    assert uow.store.events == [
        AnalysisFinished(owner_id=OWNER, run_id=requested.id, status="ready")
    ]


def _failing_run(
    service: AssessmentService, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def run(owner_id: uuid.UUID) -> object:
        raise error

    monkeypatch.setattr(service, "run", run)


async def test_a_failed_analysis_is_recorded_on_its_run_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)
    _failing_run(service, monkeypatch, BudgetExceededError("this month's budget is spent"))
    requested = await service.request_run(OWNER)

    assert await service.analyse(OWNER, requested.id) is None

    latest = await service.latest_run(OWNER)
    assert latest is not None and (latest.status, latest.error_code) == (
        "failed",
        "ai_budget_exceeded",
    )
    assert uow.store.events == [
        AnalysisFinished(
            owner_id=OWNER,
            run_id=requested.id,
            status="failed",
            error_code="ai_budget_exceeded",
        )
    ]


async def test_an_analysis_that_stops_unexpectedly_is_recorded_and_still_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(FakeAssessmentUnitOfWork())
    _failing_run(service, monkeypatch, RuntimeError("x"))
    requested = await service.request_run(OWNER)

    with pytest.raises(RuntimeError):
        await service.analyse(OWNER, requested.id)

    latest = await service.latest_run(OWNER)
    assert latest is not None and (latest.status, latest.error_code) == ("failed", "internal")


async def test_a_run_that_already_ended_does_not_analyse_again() -> None:
    gateway = FakeGateway()
    service = _service(FakeAssessmentUnitOfWork(), gateway=gateway)
    requested = await service.request_run(OWNER)
    await service.fail_run(OWNER, requested.id, code="stale", message="lost")

    assert await service.analyse(OWNER, requested.id) is None
    assert gateway.calls == []


async def test_an_unknown_run_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeAssessmentUnitOfWork()).analyse(OWNER, uuid.uuid4())


# --- the Analyze estimate (ADR 0020) ----------------------------------------


@dataclass
class _Estimate:
    cost_usd: Decimal
    model_id: str = "claude-opus-5"
    input_tokens: int = 1200
    rate_is_published: bool = True


class _PricedGateway:
    async def estimate(self, owner_id: uuid.UUID, **kwargs: Any) -> _Estimate:
        return _Estimate(cost_usd=Decimal("0.10"))


class _PricedRoleMap:
    """Prices each fit projection at $0.10, as the role map would: one per
    recommended role the build may make, plus the user's own."""

    def __init__(self, cost: dict[str, Any], custom_roles: int = 0) -> None:
        self.cost = cost
        self.custom_roles = custom_roles
        self.fits_asked: list[int | None] = []

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        return self.cost

    async def estimate_fits(
        self, owner_id: uuid.UUID, *, recommended: int | None = None
    ) -> dict[str, Any]:
        self.fits_asked.append(recommended)
        roles = (recommended or 0) + self.custom_roles
        return {
            "cost_usd": str(Decimal("0.10") * roles) if roles else "0",
            "roles": roles,
            "rate_is_published": True,
        }


def _priced(role_map_cost: dict[str, Any], custom_roles: int = 0) -> AssessmentService:
    return AssessmentService(
        FakeAssessmentUnitOfWork(),
        profile=FakeProfile(),  # type: ignore[arg-type]
        rolemap=_PricedRoleMap(role_map_cost, custom_roles),  # type: ignore[arg-type]
        gateway=_PricedGateway(),  # type: ignore[arg-type]
        confidence_threshold=0.5,
    )


async def test_analyze_is_priced_with_the_role_map_build_and_fits_that_follow_it() -> None:
    """Each call is priced at $0.10 here: one analysis, and one fit projection
    for each of the ten roles and the user's two own."""
    service = _priced(
        {
            "max_roles": 10,
            "cost_usd": "0.40",
            "model_id": "claude-opus-5",
            "rate_is_published": True,
        },
        custom_roles=2,
    )

    estimate = await service.estimate_cost(OWNER)

    assert (estimate["analysis_cost_usd"], estimate["role_map_cost_usd"]) == ("0.10", "0.40")
    assert estimate["fits_cost_usd"] == "1.20"
    assert estimate["cost_usd"] == "1.70"
    assert estimate["max_roles"] == 10
    assert estimate["rate_is_published"] is True


async def test_analyze_on_a_market_too_thin_for_a_role_costs_the_analysis_alone() -> None:
    service = _priced({"max_roles": 0, "cost_usd": "0", "model_id": None})

    estimate = await service.estimate_cost(OWNER)

    assert estimate["cost_usd"] == "0.10"
    assert (estimate["max_roles"], estimate["fits_cost_usd"]) == (0, "0")


# --- candidate roles for the role map (ADR 0024) ----------------------------


class _RecordingRoleMap:
    def __init__(self) -> None:
        self.handed: list[tuple[uuid.UUID, list[Any]]] = []
        self.strengths: list[Any] = []

    async def replace_candidates(
        self,
        owner_id: uuid.UUID,
        assessment_id: uuid.UUID,
        candidates: list[Any],
        strengths: list[Any] = (),  # type: ignore[assignment]
    ) -> list[Any]:
        self.handed.append((assessment_id, list(candidates)))
        self.strengths = list(strengths)
        return []


def _reply(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dimensions": [
            {
                "id": key,
                "name": key.title(),
                "score": 60,
                "confidence": 0.8,
                "read": "Shown by the evidence.",
                "evidence_ids": ["E1"],
            }
            for key in ("backend", "data", "infra", "testing", "delivery")
        ],
        "candidates": candidates,
    }


def _analysing(reply: dict[str, Any]) -> tuple[AssessmentService, _RecordingRoleMap, Any]:
    uow = FakeAssessmentUnitOfWork()
    rolemap = _RecordingRoleMap()
    service = AssessmentService(
        uow,
        profile=FakeProfile(),  # type: ignore[arg-type]
        rolemap=rolemap,  # type: ignore[arg-type]
        gateway=FakeGateway(reply),  # type: ignore[arg-type]
        confidence_threshold=0.5,
    )
    return service, rolemap, uow


async def test_an_analysis_hands_the_roles_it_recommends_to_the_role_map() -> None:
    service, rolemap, _uow = _analysing(
        _reply(
            [
                {
                    "title": " Backend Engineer ",
                    "description": "Builds services.",
                    "dimension_ids": ["backend", "data", "backend"],
                },
                {"title": "Data Engineer", "description": "Moves data.", "dimension_ids": ["data"]},
            ]
        )
    )

    assessment = await service.run(OWNER)

    [(assessment_id, candidates)] = rolemap.handed
    assert assessment_id == assessment.id
    assert [(c.title, c.dimension_keys) for c in candidates] == [
        ("Backend Engineer", ("backend", "data")),
        ("Data Engineer", ("data",)),
    ]
    # With what the local fit estimate weighs them by: score times confidence,
    # and no evidence (ADR 0027).
    assert {(s.dimension_key, s.read) for s in rolemap.strengths} >= {
        ("backend", "Shown by the evidence.")
    }
    assert [s.weight for s in rolemap.strengths] == pytest.approx([0.6 * 0.8] * 5)
    # And the scores themselves, which the role map scores its fits against
    # (ADR 0028).
    assert {(s.score, s.confidence) for s in rolemap.strengths} == {(60, 0.8)}


async def test_a_role_resting_on_a_dimension_the_reply_lacks_rejects_the_whole_reply() -> None:
    service, rolemap, uow = _analysing(
        _reply([{"title": "Designer", "description": "Designs.", "dimension_ids": ["taste"]}])
    )

    with pytest.raises(OutputInvalidError, match="did not produce"):
        await service.run(OWNER)

    assert rolemap.handed == [] and uow.store.assessments == {}
