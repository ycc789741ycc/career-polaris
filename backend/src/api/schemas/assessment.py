"""Assessment's wire shapes: the radar."""

from __future__ import annotations

import uuid

from advisor.assessment import AssessmentView
from api.schemas.common import ApiModel, Page, Timestamp


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


class AssessmentPage(Page[Assessment]):
    pass
