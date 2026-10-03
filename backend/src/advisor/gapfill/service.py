"""Fill the gap: the Advisor's first step (domain decision 27, ADR 0023).

Questions are written per gap of one Target — the dimensions the user is short
on, and the requirements nothing in their evidence speaks to — on the user's
key, as a job whose status the page polls (ADR 0006). The answers arrive in one
submit: the whole batch is checked, every answer is recorded as ``user_answer``
evidence through ``profile`` in one transaction, and ``GapAnswersSubmitted``
is recorded. Submitting spends nothing: the Target's gap plan and résumé read
as outdated by the new evidence until the user regenerates them (ADR 0035).
An unanswered question stays a gap.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from advisor.gapfill.domain import (
    ASKED_GAPS,
    MAX_CHOICES,
    Answer,
    AnswerType,
    AskedGap,
    DraftQuestion,
    GapAnswersSubmitted,
    GapFillError,
    GapFillUnitOfWork,
    GapQuestion,
    GapQuestionFilter,
    GapStatus,
    OwnerGapFill,
    QuestionSet,
    QuestionSetFilter,
    QuestionSetStatus,
    answer_fact,
    assert_questions_valid,
)
from advisor.profile import AnswerRecord, ProfileService
from advisor.target import DimensionGap, TargetRef, TargetService, TargetSnapshot
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.errors import DomainError, NotFoundError, TargetUnusableError, ValidationError
from kernel.logging import get_logger

__all__ = [
    "Answer",
    "GapAnswerView",
    "GapFillService",
    "GapView",
    "QuestionSetView",
    "QuestionView",
    "SubmittedView",
]

log = get_logger(__name__)

_TEMPLATE = ("gap_questions", "v1")
_UNTRUSTED = frozenset({"gaps", "evidence"})
# The evidence shown to the model, so a large profile stays one predictable call.
MAX_EVIDENCE_LINES = 60


class _Question(BaseModel):
    gap_key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=400)
    asked_because: str = Field(min_length=1, max_length=400)
    answer_type: Literal["choice", "free_text", "both"]
    choices: list[str] = Field(default_factory=list, max_length=MAX_CHOICES)


class _Questions(BaseModel):
    questions: list[_Question] = Field(min_length=1, max_length=12)


@dataclass(frozen=True, slots=True)
class GapView:
    key: str
    label: str
    status: str
    lift: int


@dataclass(frozen=True, slots=True)
class QuestionView:
    id: uuid.UUID
    gap_key: str
    text: str
    asked_because: str
    answer_type: str
    choices: tuple[str, ...]
    # Set once submitted: the evidence the answer became.
    evidence_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class QuestionSetView:
    id: uuid.UUID
    target: TargetRef
    label: str
    status: str
    gaps: tuple[GapView, ...]
    questions: tuple[QuestionView, ...]
    model_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class GapAnswerView:
    """One answer the user submitted, and the gap it was asked about: what a
    gap plan may cite for that gap (ADR 0036)."""

    gap_key: str
    evidence_id: uuid.UUID
    answered_at: datetime


@dataclass(frozen=True, slots=True)
class SubmittedView:
    set_id: uuid.UUID
    evidence_ids: tuple[uuid.UUID, ...]
    # Questions left blank, whose gaps stay open.
    skipped: int


class GapFillService:
    def __init__(
        self,
        uow: GapFillUnitOfWork,
        *,
        target: TargetService,
        profile: ProfileService,
        gateway: AiGateway,
    ) -> None:
        self._uow = uow
        self._target = target
        self._profile = profile
        self._gateway = gateway

    async def current(self, owner_id: uuid.UUID, ref: TargetRef) -> QuestionSetView | None:
        """The Target's latest set that is not superseded, if it has one."""
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.sets.get_list(
                _for_target(
                    ref,
                    statuses=(
                        QuestionSetStatus.WRITING,
                        QuestionSetStatus.READY,
                        QuestionSetStatus.FAILED,
                    ),
                ),
                page_size=1,
            )
            if not found:
                return None
            return await _view(mine, found[0])

    async def get(self, owner_id: uuid.UUID, set_id: uuid.UUID) -> QuestionSetView:
        async with self._uow.for_owner(owner_id) as mine:
            return await _view(mine, await _owned(mine, set_id))

    async def get_answers(self, owner_id: uuid.UUID, ref: TargetRef) -> tuple[GapAnswerView, ...]:
        """Every answer submitted for this Target, in any of its sets, with the
        gap each was asked about, newest first (ADR 0036). An answer whose
        evidence is gone is left out. One user's sets for one Target: few."""
        async with self._uow.for_owner(owner_id) as mine:
            sets = await mine.sets.get_list(_for_target(ref))
            questions = (
                await mine.questions.get_list(GapQuestionFilter(set_ids=tuple(s.id for s in sets)))
                if sets
                else []
            )
        answers = [
            GapAnswerView(gap_key=q.gap_key, evidence_id=q.evidence_id, answered_at=q.answered_at)
            for q in questions
            if q.evidence_id is not None and q.answered_at is not None
        ]
        if not answers:
            return ()
        owned = await self._profile.evidence_ids(owner_id)
        return tuple(
            sorted(
                (a for a in answers if str(a.evidence_id) in owned),
                key=lambda a: (a.answered_at, str(a.evidence_id)),
                reverse=True,
            )
        )

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        """Priced before anything is spent."""
        snapshot = await self._target.snapshot(owner_id, ref)
        estimate = await self._gateway.estimate(
            owner_id,
            task="gapfill.write",
            template=load_template(*_TEMPLATE),
            inputs=await self._inputs(owner_id, snapshot, _asked(snapshot)),
            untrusted=_UNTRUSTED,
        )
        return {
            "cost_usd": str(estimate.cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
        }

    async def request(self, owner_id: uuid.UUID, ref: TargetRef) -> QuestionSetView:
        """Record a set as writing; the caller queues ``write``.

        The Target is resolved here, so one with nothing to ask about is
        refused now. A newer set supersedes the Target's earlier ones; answers
        already submitted stay evidence.
        """
        snapshot = await self._target.snapshot(owner_id, ref)
        gaps = _asked(snapshot)
        if not gaps:
            raise TargetUnusableError(
                f"you already clear everything {snapshot.label} asks for; there is nothing to ask"
            )
        async with self._uow.for_owner(owner_id) as mine:
            for earlier in await mine.sets.get_list(_for_target(ref)):
                if earlier.status is not QuestionSetStatus.SUPERSEDED:
                    earlier.supersede()
                    await mine.sets.update(earlier)
            created = await mine.sets.create(
                QuestionSet.requested(
                    owner_id=owner_id,
                    role_id=ref.role_uuid,
                    job_posting_id=ref.opening_uuid,
                    private_job_posting_id=ref.own_posting_uuid,
                    label=snapshot.label,
                    gaps=gaps,
                    at=utcnow(),
                )
            )
            return await _view(mine, created)

    async def write(self, owner_id: uuid.UUID, set_id: uuid.UUID) -> None:
        """The worker job. An expected failure is recorded on the set with its
        stable code and not retried: a retry would spend the key again."""
        async with self._uow.for_owner(owner_id) as mine:
            found = await _owned(mine, set_id)
        if found.status is not QuestionSetStatus.WRITING:
            return
        try:
            await self._write(owner_id, found)
        except DomainError as exc:
            log.warning("gapfill.write_failed", set_id=str(set_id), code=str(exc.code))
            await self._fail(owner_id, set_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fail(
                owner_id, set_id, code="internal", message="writing the questions stopped"
            )
            raise

    async def submit(
        self, owner_id: uuid.UUID, set_id: uuid.UUID, answers: Sequence[Answer]
    ) -> SubmittedView:
        """Record every answer in the batch as evidence, or none of them.

        The whole batch is checked before anything is stored; a blank answer is
        skipped and its gap stays open. A set is submitted once.
        """
        async with self._uow.for_owner(owner_id) as mine:
            found = await _owned(mine, set_id)
            questions = await _questions(mine, set_id)
        if found.status is not QuestionSetStatus.READY:
            raise ValidationError("these questions are not ready to answer", set_id=str(set_id))
        if found.submitted_at is not None:
            raise ValidationError("these answers were already submitted", set_id=str(set_id))

        by_id = {q.id: q for q in questions}
        facts: dict[uuid.UUID, str] = {}
        for answer in answers:
            question = by_id.get(answer.question_id)
            if question is None:
                raise ValidationError(
                    "an answer is for a question not in this set",
                    question_id=str(answer.question_id),
                )
            if answer.question_id in facts:
                raise ValidationError("a question was answered twice")
            try:
                fact = answer_fact(
                    text=question.text,
                    answer_type=question.answer_type,
                    choices=question.choices,
                    answer=answer,
                )
            except GapFillError as exc:
                raise ValidationError(str(exc), question_id=str(question.id)) from exc
            if fact is not None:
                facts[question.id] = fact
        if not facts:
            raise ValidationError("answer at least one question before submitting")

        stored = await self._profile.record_answers(
            owner_id,
            [AnswerRecord(question_id=str(qid), fact=fact) for qid, fact in facts.items()],
        )
        evidence = dict(zip(facts, (e.id for e in stored), strict=True))
        now = utcnow()
        async with self._uow.for_owner(owner_id) as mine:
            for question_id, evidence_id in evidence.items():
                question = by_id[question_id]
                question.answered(evidence_id, now)
                await mine.questions.update(question)
            found.submitted(now)
            await mine.sets.update(found)
            mine.record(
                GapAnswersSubmitted(
                    owner_id=owner_id,
                    set_id=set_id,
                    role_id=found.role_id,
                    job_posting_id=found.job_posting_id,
                    private_job_posting_id=found.private_job_posting_id,
                    evidence_ids=tuple(str(e) for e in evidence.values()),
                )
            )
        log.info("gapfill.submitted", set_id=str(set_id), answered=len(evidence))
        return SubmittedView(
            set_id=set_id,
            evidence_ids=tuple(evidence.values()),
            skipped=len(questions) - len(evidence),
        )

    # -- internals ----------------------------------------------------------

    async def _write(self, owner_id: uuid.UUID, found: QuestionSet) -> None:
        ref = _ref_of(found)
        snapshot = await self._target.snapshot(owner_id, ref)
        result = await self._gateway.run(
            owner_id,
            task="gapfill.write",
            template=load_template(*_TEMPLATE),
            inputs=await self._inputs(owner_id, snapshot, found.gaps),
            output_schema=_Questions,
            untrusted=_UNTRUSTED,
        )
        drafts = [
            DraftQuestion(
                gap_key=q.gap_key,
                text=q.text.strip(),
                asked_because=q.asked_because.strip(),
                answer_type=AnswerType(q.answer_type),
                choices=tuple(c.strip() for c in q.choices if c.strip()),
            )
            for q in result.value.questions
        ]
        try:
            assert_questions_valid(drafts, found.gaps)
        except GapFillError as exc:
            raise ValidationError(str(exc)) from exc

        gaps = {gap.key: gap for gap in found.gaps}
        order = {gap.key: index for index, gap in enumerate(found.gaps)}
        ranked = sorted(drafts, key=lambda d: order[d.gap_key])
        async with self._uow.for_owner(owner_id) as mine:
            for position, draft in enumerate(ranked):
                gap = gaps[draft.gap_key]
                await mine.questions.create(
                    GapQuestion(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        set_id=found.id,
                        position=position,
                        gap_key=gap.key,
                        gap_label=gap.label,
                        gap_status=gap.status,
                        lift=gap.lift,
                        text=draft.text,
                        asked_because=draft.asked_because,
                        answer_type=draft.answer_type,
                        choices=draft.choices,
                    )
                )
            stored = await _owned(mine, found.id)
            stored.written(
                model_id=result.model_id, template_version=result.template_version, at=utcnow()
            )
            await mine.sets.update(stored)

    async def _inputs(
        self, owner_id: uuid.UUID, snapshot: TargetSnapshot, gaps: Sequence[AskedGap]
    ) -> dict[str, str]:
        profile = await self._profile.snapshot(owner_id)
        dimensions = {d.key: d for d in snapshot.dimensions}
        lines = []
        for gap in gaps:
            dimension = dimensions.get(gap.key)
            detail = (
                f"scores {dimension.user_score}, the job expects {dimension.target_score}"
                if dimension is not None
                else "nothing in the evidence speaks to it"
            )
            lines.append(
                f"- {gap.key} — {gap.label} ({gap.status}, worth up to {gap.lift} fit "
                f"points): {detail}"
            )
        evidence = [
            f"- ({e.source}) {e.reference}: {e.fact}" for e in profile.evidence[:MAX_EVIDENCE_LINES]
        ]
        return {
            "target": snapshot.label,
            "gaps": "\n".join(lines),
            "evidence": "\n".join(evidence) or "(no evidence yet)",
        }

    async def _fail(
        self, owner_id: uuid.UUID, set_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.sets.get(set_id)
            if found is not None and found.status is QuestionSetStatus.WRITING:
                found.failed(code=code, message=message)
                await mine.sets.update(found)


# --- helpers ---------------------------------------------------------------


def _asked(snapshot: TargetSnapshot) -> tuple[AskedGap, ...]:
    """The Target's costliest open gaps, as the plan ranks them."""
    return tuple(
        AskedGap(key=gap.key, label=gap.name, status=GapStatus.PARTIAL, lift=gap.lift)
        if isinstance(gap, DimensionGap)
        else AskedGap(key=gap.key, label=gap.statement, status=GapStatus.NO_EVIDENCE, lift=gap.lift)
        for gap in snapshot.open_gaps[:ASKED_GAPS]
    )


def _ref_of(found: QuestionSet) -> TargetRef:
    return TargetRef.of(found.role_id, found.job_posting_id, found.private_job_posting_id)


def _for_target(
    ref: TargetRef, *, statuses: tuple[QuestionSetStatus, ...] | None = None
) -> QuestionSetFilter:
    if ref.is_own_posting:
        return QuestionSetFilter(private_job_posting_id=ref.own_posting_uuid, statuses=statuses)
    opening = ref.opening_uuid
    return QuestionSetFilter(
        role_id=ref.role_uuid,
        job_posting_id=opening,
        role_only=opening is None,
        statuses=statuses,
    )


async def _owned(mine: OwnerGapFill, set_id: uuid.UUID) -> QuestionSet:
    found = await mine.sets.get(set_id)
    if found is None:
        raise NotFoundError("question set not found", set_id=str(set_id))
    return found


async def _questions(mine: OwnerGapFill, set_id: uuid.UUID) -> list[GapQuestion]:
    found = await mine.questions.get_list(GapQuestionFilter(set_ids=(set_id,)))
    return sorted(found, key=lambda q: q.position)


async def _view(mine: OwnerGapFill, found: QuestionSet) -> QuestionSetView:
    questions = await _questions(mine, found.id)
    return QuestionSetView(
        id=found.id,
        target=_ref_of(found),
        label=found.label,
        status=str(found.status),
        gaps=tuple(GapView(g.key, g.label, str(g.status), g.lift) for g in found.gaps),
        questions=tuple(
            QuestionView(
                id=q.id,
                gap_key=q.gap_key,
                text=q.text,
                asked_because=q.asked_because,
                answer_type=str(q.answer_type),
                choices=q.choices,
                evidence_id=q.evidence_id,
            )
            for q in questions
        ),
        model_id=found.model_id,
        error_code=found.error_code,
        error_message=found.error_message,
        created_at=found.created_at,
        submitted_at=found.submitted_at,
    )
