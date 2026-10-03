"""Fill the gap's wire shapes: the questions for one Target's gaps, and the one
submit that turns the answers into evidence (ADR 0023)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from advisor.gapfill import GapView, QuestionSetView, QuestionView, SubmittedView
from api.schemas.common import ApiModel, JobError, RequestModel, Timestamp
from api.schemas.target import TargetFields, TargetRefBody

# One user's answers for one set: a handful per gap, a few gaps.
MAX_ANSWERS = 24


class QuestionSetRequest(TargetFields):
    """A role and optionally one opening in it (ADR 0022), or a posting of the
    user's own."""


class Gap(ApiModel):
    key: str
    label: str
    # `partial`: short of what the role expects. `no_evidence`: nothing speaks
    # to it either way.
    status: Literal["partial", "no_evidence"]
    # Fit points closing it alone is worth ("up to +9 fit pts").
    lift: int

    @classmethod
    def from_view(cls, gap: GapView) -> Gap:
        return cls(key=gap.key, label=gap.label, status=gap.status, lift=gap.lift)


class GapQuestion(ApiModel):
    id: uuid.UUID
    gap_key: str
    text: str
    asked_because: str
    answer_type: Literal["choice", "free_text", "both"]
    choices: list[str]
    # Set once submitted: the evidence the answer became.
    evidence_id: uuid.UUID | None

    @classmethod
    def from_view(cls, q: QuestionView) -> GapQuestion:
        return cls(
            id=q.id,
            gap_key=q.gap_key,
            text=q.text,
            asked_because=q.asked_because,
            answer_type=q.answer_type,
            choices=list(q.choices),
            evidence_id=q.evidence_id,
        )


class QuestionSet(ApiModel):
    """The questions for one Target's gaps; the page polls it while it is
    ``writing`` (ADR 0006)."""

    id: uuid.UUID
    target: TargetRefBody
    label: str
    status: Literal["writing", "ready", "failed", "superseded"]
    gaps: list[Gap]
    questions: list[GapQuestion]
    model_id: str | None
    error: JobError | None
    created_at: Timestamp
    submitted_at: Timestamp | None

    @classmethod
    def from_view(cls, found: QuestionSetView) -> QuestionSet:
        return cls(
            id=found.id,
            target=TargetRefBody.from_ref(found.target),
            label=found.label,
            status=found.status,
            gaps=[Gap.from_view(g) for g in found.gaps],
            questions=[GapQuestion.from_view(q) for q in found.questions],
            model_id=found.model_id,
            error=JobError.of(found.error_code, found.error_message),
            created_at=found.created_at,
            submitted_at=found.submitted_at,
        )


class AnswerBody(RequestModel):
    question_id: uuid.UUID
    choice: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=2000)


class AnswersRequest(RequestModel):
    """Every answer at once; a question left out stays a gap."""

    answers: list[AnswerBody] = Field(min_length=1, max_length=MAX_ANSWERS)


class Submitted(ApiModel):
    set_id: uuid.UUID
    # How many answers became evidence ("Your answers" on Sources).
    answered: int
    # Questions left blank, whose gaps stay open.
    skipped: int

    @classmethod
    def from_view(cls, done: SubmittedView) -> Submitted:
        return cls(set_id=done.set_id, answered=len(done.evidence_ids), skipped=done.skipped)
