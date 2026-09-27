"""Assessment use cases against in-memory storage: what they store and announce,
with no database and no model."""

from __future__ import annotations

import uuid
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
    TargetScore,
    evaluate,
)
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.assessment.fakes import FakeAssessmentUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeProfile:
    def __init__(self) -> None:
        self.answers: list[tuple[str, str]] = []

    async def record_answer(
        self, owner_id: uuid.UUID, *, question_id: str, question: str, answer: str
    ) -> None:
        self.answers.append((question, answer))


def _service(
    uow: FakeAssessmentUnitOfWork, profile: FakeProfile | None = None
) -> AssessmentService:
    return AssessmentService(
        uow,
        profile=profile or FakeProfile(),  # type: ignore[arg-type]
        rolemap=None,  # type: ignore[arg-type]
        market=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        confidence_threshold=0.5,
    )


def _dimension(key: str, name: str, score: int = 60) -> DimensionScore:
    return DimensionScore(
        dimension_id=key,
        name=name,
        short_name=name[:8],
        score=score,
        confidence=0.8,
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
    history = await service.history(OWNER)
    assert [h.profile_version for h in history] == [2, 1]


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

    first, second = await service.questions(OWNER)
    assert (first.text, second.text) == ("First?", "Second?")

    await service.answer(OWNER, first.id, "yes")

    assert [q.text for q in await service.questions(OWNER)] == ["Second?"]
    assert len(await service.questions(OWNER, unanswered_only=False)) == 2
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
