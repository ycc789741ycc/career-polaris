"""Fill the gap's entities: the questions written for one Target's gaps.

Plain data with the rules that belong to it; ``advisor.gapfill.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.gapfill.domain.questions import AnswerType, AskedGap, GapStatus


class QuestionSetStatus(StrEnum):
    """A set is written in the background, so it is recorded before it starts
    and the page polls it (ADR 0006). A newer set for the same Target
    supersedes it."""

    WRITING = "writing"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class QuestionSet:
    """The questions written for one Target's gaps (domain decision 27)."""

    id: uuid.UUID
    owner_id: uuid.UUID
    # The Target (ADR 0022): a role, and optionally one opening in it.
    role_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    label: str
    status: QuestionSetStatus
    gaps: tuple[AskedGap, ...]
    created_at: datetime
    model_id: str | None = None
    template_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    written_at: datetime | None = None
    submitted_at: datetime | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        role_id: uuid.UUID,
        job_posting_id: uuid.UUID | None,
        label: str,
        gaps: tuple[AskedGap, ...],
        at: datetime,
    ) -> QuestionSet:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            label=label[:400],
            status=QuestionSetStatus.WRITING,
            gaps=gaps,
            created_at=at,
        )

    @property
    def is_open(self) -> bool:
        """Still the Target's current set: writing, or written and not yet
        submitted."""
        return self.status is QuestionSetStatus.WRITING or (
            self.status is QuestionSetStatus.READY and self.submitted_at is None
        )

    def written(self, *, model_id: str, template_version: str, at: datetime) -> None:
        self.status = QuestionSetStatus.READY
        self.model_id = model_id
        self.template_version = template_version
        self.written_at = at

    def failed(self, *, code: str, message: str) -> None:
        self.status = QuestionSetStatus.FAILED
        self.error_code = code
        self.error_message = message

    def supersede(self) -> None:
        self.status = QuestionSetStatus.SUPERSEDED

    def submitted(self, at: datetime) -> None:
        self.submitted_at = at


@dataclass(slots=True)
class GapQuestion:
    """One question about one gap. Its answer is not stored here while the
    user types: it arrives with the one submit, and becomes evidence."""

    id: uuid.UUID
    owner_id: uuid.UUID
    set_id: uuid.UUID
    position: int
    gap_key: str
    gap_label: str
    gap_status: GapStatus
    lift: int
    text: str
    asked_because: str
    answer_type: AnswerType
    choices: tuple[str, ...]
    evidence_id: uuid.UUID | None = None
    answered_at: datetime | None = None

    def answered(self, evidence_id: uuid.UUID, at: datetime) -> None:
        self.evidence_id = evidence_id
        self.answered_at = at
