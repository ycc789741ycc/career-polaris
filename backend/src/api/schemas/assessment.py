"""Assessment's wire shapes: the radar and the fits."""

from __future__ import annotations

import uuid
from typing import Literal

from advisor.assessment import (
    AssessmentView,
    FitView,
    MatchedPostingView,
)
from api.schemas.common import ApiModel, Page, Salary, Timestamp


class Dimension(ApiModel):
    key: str
    name: str
    short_name: str
    score: int
    confidence: float
    read: str
    evidence_ids: list[str]
    # Confidence is below the threshold: the evidence is not enough to be
    # sure of this score yet, and Strengths points to Sources for more.
    needs_more_evidence: bool


class Assessment(ApiModel):
    id: uuid.UUID
    profile_version: int
    # The profile's evidence has changed since this ran: re-analyse to catch up.
    is_out_of_date: bool
    model_id: str
    template_version: str
    created_at: Timestamp
    dimensions: list[Dimension]
    # How well the evidence backs the scores overall, 0 to 1: the mean of the
    # dimensions' confidence (domain decision 28). Null with no dimensions.
    profile_confidence: float | None

    @classmethod
    def from_view(cls, assessment: AssessmentView) -> Assessment:
        return cls(
            id=assessment.id,
            profile_version=assessment.profile_version,
            is_out_of_date=assessment.is_out_of_date,
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
                    needs_more_evidence=d.needs_more_evidence,
                )
                for d in assessment.dimensions
            ],
            profile_confidence=assessment.profile_confidence,
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
            source_kind=m.source_kind,
        )


class AssessmentPage(Page[Assessment]):
    pass


class FitPage(Page[Fit]):
    pass


class MatchedPostingPage(Page[MatchedPosting]):
    pass
