"""Assessment use cases against in-memory storage: what they store and announce,
with no database and no model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from advisor.assessment import AssessmentService
from advisor.assessment.domain import (
    AssessmentCompleted,
    DimensionsChanged,
    DimensionScore,
    FollowUpQuestion,
    LineageKind,
    QuestionAnswered,
    QuestionRoundStatus,
    QuestionRoundTrigger,
    QuestionsRaised,
    TargetScore,
    evaluate,
)
from kernel.errors import BudgetExceededError, NotFoundError, ValidationError
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


class FakeProfile:
    def __init__(self) -> None:
        self.answers: list[tuple[str, str]] = []

    async def record_answer(
        self, owner_id: uuid.UUID, *, question_id: str, question: str, answer: str
    ) -> None:
        self.answers.append((question, answer))

    async def snapshot(self, owner_id: uuid.UUID) -> _Snapshot:
        return _Snapshot(evidence=(_Evidence("e1", "github", "GitHub · api", "12 merged PRs"),))


@dataclass
class _Result:
    value: Any
    model_id: str = "model"
    template_version: str = "v1"


class FakeGateway:
    """Answers with a canned reply, or fails the way the real gateway can."""

    def __init__(self, reply: dict[str, Any] | None = None, error: Exception | None = None):
        self.reply = reply or {"questions": []}
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
        market=None,  # type: ignore[arg-type]
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


async def test_questions_come_oldest_first_and_an_answer_becomes_evidence() -> None:
    uow = FakeAssessmentUnitOfWork()
    profile = FakeProfile()
    service = _service(uow, profile)
    assessment_id = await _assess(service, [_dimension("api", "APIs")])
    async with uow.for_owner(OWNER) as mine:
        for text in ("First?", "Second?"):
            await mine.questions.create(
                FollowUpQuestion(
                    id=uuid.uuid4(),
                    owner_id=OWNER,
                    assessment_id=assessment_id,
                    dimension_key="api",
                    text=text,
                    why="thin evidence",
                    options=("yes", "no"),
                )
            )
    uow.store.events.clear()

    first, second = (await service.questions(OWNER)).items
    assert (first.text, second.text) == ("First?", "Second?")

    await service.answer(OWNER, first.id, "yes")

    assert [q.text for q in (await service.questions(OWNER)).items] == ["Second?"]
    assert (await service.questions(OWNER, unanswered_only=False)).total == 2
    assert profile.answers == [("First?", "yes")]
    assert uow.store.events == [
        QuestionAnswered(owner_id=OWNER, question_id=first.id, dimension_key="api")
    ]
    with pytest.raises(NotFoundError):
        await _service(uow).answer(OTHER, second.id, "no")


async def _fit(
    service: AssessmentService,
    *,
    score_target: int,
    role_id: uuid.UUID | None = None,
    posting_id: uuid.UUID | None = None,
) -> None:
    targets = [TargetScore(dimension_id="api", target=score_target)]
    result: Any = evaluate(user_scores={"api": 60}, targets=targets, uncovered=[])
    await service._store_fit(
        OWNER,
        assessment_id=uuid.uuid4(),
        role_id=role_id,
        private_posting_id=posting_id,
        fit=result,
        targets=targets,
        requirements=(),
        requirement_map={},
        reasoning="because",
        model_id="model",
        template_version="v1",
    )


async def test_the_current_fit_is_the_newest_per_role_or_posting() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)
    role, posting = uuid.uuid4(), uuid.uuid4()

    await _fit(service, score_target=90, role_id=role)
    await _fit(service, score_target=60, role_id=role)
    await _fit(service, score_target=70, posting_id=posting)

    fits = await service.fits(OWNER)
    assert len(fits) == 2 and len(uow.store.fits) == 3
    by_target = {f.role_id or f.private_posting_id: f for f in fits}
    assert by_target[role].target_profile == {"api": 60}
    assert by_target[posting].private_posting_id == posting


async def test_a_fit_is_for_exactly_one_role_or_posting() -> None:
    service = _service(FakeAssessmentUnitOfWork())
    with pytest.raises(ValidationError):
        await _fit(service, score_target=60)
    with pytest.raises(ValidationError):
        await _fit(service, score_target=60, role_id=uuid.uuid4(), posting_id=uuid.uuid4())


# -- question rounds ----------------------------------------------------------


def _question(assessment_id: uuid.UUID, text: str) -> FollowUpQuestion:
    return FollowUpQuestion(
        id=uuid.uuid4(),
        owner_id=OWNER,
        assessment_id=assessment_id,
        dimension_key="api",
        text=text,
        why="thin evidence",
        options=("yes", "no"),
    )


def _asks(*dimension_ids: str) -> dict[str, Any]:
    return {
        "questions": [
            {
                "dimension_id": key,
                "text": f"About {key}?",
                "why": "Only one repository shows it.",
                "options": ["Led it", "Helped", "Not me"],
            }
            for key in dimension_ids
        ]
    }


async def test_no_round_is_opened_before_an_analysis_or_when_nothing_is_thin() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)

    assert await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE) is None

    await _assess(service, [_dimension("api", "APIs", confidence=0.9)])
    assert await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE) is None
    assert uow.store.rounds == {} and await service.latest_round(OWNER) is None


async def test_a_new_request_supersedes_the_round_still_generating() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow)
    await _assess(service, [_dimension("api", "APIs", confidence=0.3)])

    first = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.ASSESSMENT)
    second = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)

    assert first and second and first != second
    assert uow.store.rounds[first].status is QuestionRoundStatus.SUPERSEDED
    latest = await service.latest_round(OWNER)
    assert latest is not None and latest.id == second
    assert (latest.status, latest.trigger) == ("generating", "evidence")
    assert await service.latest_round(OTHER) is None


async def test_a_round_replaces_open_questions_and_keeps_answered_ones() -> None:
    uow = FakeAssessmentUnitOfWork()
    # A question for a confident dimension is dropped: only thin ones are asked.
    gateway = FakeGateway(reply=_asks("api", "db"))
    service = _service(uow, gateway=gateway)
    assessment_id = await _assess(
        service, [_dimension("api", "APIs", confidence=0.3), _dimension("db", "Data")]
    )
    async with uow.for_owner(OWNER) as mine:
        for text in ("Old open?", "Old answered?"):
            await mine.questions.create(_question(assessment_id, text))
    answered = next(q for q in uow.store.questions.values() if q.text == "Old answered?")
    await service.answer(OWNER, answered.id, "yes")
    uow.store.events.clear()

    round_id = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)
    assert round_id is not None
    await service.generate_questions(OWNER, round_id)

    assert [q.text for q in (await service.questions(OWNER)).items] == ["About api?"]
    every = [q.text for q in (await service.questions(OWNER, unanswered_only=False)).items]
    assert sorted(every) == ["About api?", "Old answered?"]
    asked = gateway.calls[0]["low_confidence_dimensions"]
    assert "- api (APIs): scored 60, confidence 0.30" in asked and "db" not in asked
    latest = await service.latest_round(OWNER)
    assert latest is not None
    assert (latest.status, latest.question_count, latest.error_code) == ("ready", 1, None)
    assert latest.finished_at is not None
    assert uow.store.events == [
        QuestionsRaised(owner_id=OWNER, assessment_id=assessment_id, count=1)
    ]


async def test_a_superseded_round_never_calls_the_model() -> None:
    uow = FakeAssessmentUnitOfWork()
    gateway = FakeGateway(reply=_asks("api"))
    service = _service(uow, gateway=gateway)
    await _assess(service, [_dimension("api", "APIs", confidence=0.3)])
    stale = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)
    await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)
    assert stale is not None

    await service.generate_questions(OWNER, stale)

    assert gateway.calls == [] and (await service.questions(OWNER)).items == ()


async def test_a_budget_failure_is_recorded_on_the_round_not_raised() -> None:
    uow = FakeAssessmentUnitOfWork()
    gateway = FakeGateway(error=BudgetExceededError("this month's budget is spent"))
    service = _service(uow, gateway=gateway)
    await _assess(service, [_dimension("api", "APIs", confidence=0.3)])
    round_id = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)
    assert round_id is not None

    await service.generate_questions(OWNER, round_id)

    latest = await service.latest_round(OWNER)
    assert latest is not None and latest.status == "failed"
    assert (latest.error_code, latest.error_message) == (
        "ai_budget_exceeded",
        "this month's budget is spent",
    )


async def test_an_unexpected_failure_is_recorded_and_still_raised() -> None:
    uow = FakeAssessmentUnitOfWork()
    service = _service(uow, gateway=FakeGateway(error=RuntimeError("boom")))
    await _assess(service, [_dimension("api", "APIs", confidence=0.3)])
    round_id = await service.request_questions(OWNER, trigger=QuestionRoundTrigger.EVIDENCE)
    assert round_id is not None

    with pytest.raises(RuntimeError):
        await service.generate_questions(OWNER, round_id)

    latest = await service.latest_round(OWNER)
    assert latest is not None and (latest.status, latest.error_code) == ("failed", "internal")
