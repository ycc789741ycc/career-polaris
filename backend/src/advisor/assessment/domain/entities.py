"""Assessment's entities: this user's dimensions, the assessments and scores
taken against them, and the analyses that produce them. Fits against roles
belong to the role map (ADR 0028).

Assessments and scores are immutable snapshots: each records the profile
version, model and template it came from, so a stale one can be detected
(domain section 2.4). ``advisor.assessment.infra`` maps these to and from the
database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.assessment.domain.dimensions import LineageKind


@dataclass(slots=True)
class SkillDimension:
    """One axis of *this user's* skills; there is no global taxonomy.

    ``key`` is reused across re-assessments, which is what lets two
    assessments be compared to show progress.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    key: str
    name: str
    short_name: str
    retired_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def rename(self, *, name: str, short_name: str) -> None:
        """Seen again: take the latest name, and it is live again."""
        self.name = name
        self.short_name = short_name
        self.retired_at = None

    def retire(self, at: datetime) -> None:
        self.retired_at = at


@dataclass(slots=True)
class SkillAssessment:
    id: uuid.UUID
    owner_id: uuid.UUID
    profile_version: int
    model_id: str
    template_version: str
    created_at: datetime | None = None


@dataclass(slots=True)
class AssessedScore:
    """One dimension's score within one assessment."""

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    dimension_key: str
    score: int
    confidence: float
    read: str
    evidence_ids: tuple[str, ...]


@dataclass(slots=True)
class DimensionChange:
    """A dimension added, renamed or merged away, so radar history lines up."""

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    kind: LineageKind
    dimension_key: str
    from_keys: tuple[str, ...] = ()
    previous_name: str | None = None
    recorded_at: datetime | None = None


class AnalysisRunStatus(StrEnum):
    """An analysis runs in the background, so it is recorded before it starts
    and the page polls it (ADR 0006, ADR 0018)."""

    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class AnalysisRun:
    """One request to analyse this user's evidence. The assessment it writes
    is a separate snapshot; this only says whether it is still being made, and
    why it could not be."""

    id: uuid.UUID
    owner_id: uuid.UUID
    status: AnalysisRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def requested(cls, *, owner_id: uuid.UUID, at: datetime) -> AnalysisRun:
        return cls(
            id=uuid.uuid4(), owner_id=owner_id, status=AnalysisRunStatus.RUNNING, started_at=at
        )

    @property
    def is_running(self) -> bool:
        return self.status is AnalysisRunStatus.RUNNING

    def ready(self, at: datetime) -> None:
        self.status = AnalysisRunStatus.READY
        self.finished_at = at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = AnalysisRunStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.finished_at = at
