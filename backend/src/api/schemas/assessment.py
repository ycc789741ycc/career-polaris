"""Assessment's wire shapes: the radar, the follow-up questions and the fits."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from advisor.assessment import (
    AssessmentView,
    FitView,
    MatchedPostingView,
    QuestionRoundView,
    QuestionView,
)
from api.schemas.common import ApiModel, JobError, RequestModel, Salary, Timestamp


class AnswerRequest(RequestModel):
    answer: str = Field(min_length=1)


class Dimension(ApiModel):
    key: str
    name: str
    short_name: str
    score: int
    confidence: float
    read: str
    evidence_ids: list[str]


class Assessment(ApiModel):
    id: uuid.UUID
    profile_version: int
    model_id: str
    template_version: str
    created_at: Timestamp
    dimensions: list[Dimension]

    @classmethod
    def from_view(cls, assessment: AssessmentView) -> Assessment:
        return cls(
            id=assessment.id,
            profile_version=assessment.profile_version,
            model_id=assessment.model_id,
            template_version=assessment.template_version,
            created_at=assessment.created_at,
            dimensions=[
                Dimension(
                    key=d.key,
                    name=d.name,
                    short_name=d.short_name,
                    score=d.score,
                    confidence=d.confidence,
                    read=d.read,
                    evidence_ids=list(d.evidence_ids),
                )
                for d in assessment.dimensions
            ],
        )


class Question(ApiModel):
    id: uuid.UUID
    dimension_key: str
    text: str
    # Every question says what it is for and which dimension it moves.
    why: str
    options: list[str]
    answer: str | None

    @classmethod
    def from_view(cls, q: QuestionView) -> Question:
        return cls(
            id=q.id,
            dimension_key=q.dimension_key,
            text=q.text,
            why=q.why,
            options=list(q.options),
            answer=q.answer,
        )


class QuestionStatus(ApiModel):
    """The newest question round, which the page polls while it is
    ``generating`` (ADR 0006, ADR 0012)."""

    id: uuid.UUID
    status: Literal["generating", "ready", "failed", "superseded"]
    # `evidence` after a sync or upload, `assessment` after an analysis.
    trigger: Literal["evidence", "assessment"]
    question_count: int
    created_at: Timestamp
    finished_at: Timestamp | None
    error: JobError | None

    @classmethod
    def from_view(cls, found: QuestionRoundView) -> QuestionStatus:
        return cls(
            id=found.id,
            status=found.status,
            trigger=found.trigger,
            question_count=found.question_count,
            created_at=found.created_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
        )


class FitGap(ApiModel):
    dimension_key: str
    user_score: int
    target_score: int
    delta: int


class UncoveredRequirement(ApiModel):
    statement: str
    weight: float


class Fit(ApiModel):
    """A bubble's size. Fit belongs to the User x Role pair, never to the role."""

    role_id: uuid.UUID | None
    private_posting_id: uuid.UUID | None
    score: int
    reasoning: str
    gaps: list[FitGap]
    # Requirements with no matching dimension: no evidence at all, which is
    # different from a low score.
    uncovered: list[UncoveredRequirement]
    model_id: str
    computed_at: Timestamp

    @classmethod
    def from_view(cls, f: FitView) -> Fit:
        return cls(
            role_id=f.role_id,
            private_posting_id=f.private_posting_id,
            score=f.score,
            reasoning=f.reasoning,
            # Stored as the JSON they were written as; validated on the way out.
            gaps=[FitGap.model_validate(g) for g in f.gaps],
            uncovered=[UncoveredRequirement.model_validate(u) for u in f.uncovered],
            model_id=f.model_id,
            computed_at=f.created_at,
        )


class MatchedPosting(ApiModel):
    """An opening inside one of the user's roles, ranked by that role's fit."""

    posting_id: uuid.UUID
    role_id: uuid.UUID
    role_name: str
    title: str
    company_name: str
    location: str | None
    url: str | None
    salary: Salary | None
    # The role's fit: a posting's own requirements do not move it yet.
    fit: int | None
    fit_basis: Literal["role"] = "role"
    subscription_id: uuid.UUID | None
    # atsBoard, jsonLd or publicApi; never a site that forbids crawling.
    source_kind: str | None

    @classmethod
    def from_view(cls, m: MatchedPostingView) -> MatchedPosting:
        return cls(
            posting_id=m.posting_id,
            role_id=m.role_id,
            role_name=m.role_name,
            title=m.title,
            company_name=m.company_name,
            location=m.location,
            url=m.url,
            salary=Salary.of(m.salary),
            fit=m.fit,
            subscription_id=m.subscription_id,
            source_kind=m.source_kind,
        )
