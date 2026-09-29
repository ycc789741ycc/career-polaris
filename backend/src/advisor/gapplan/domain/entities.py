"""The gap plan's entities: plans, their milestones and their tasks.

A plan holds its Target as a kind and one id, plus the frozen snapshot of what
that Target required, so it survives posting expiry and re-clustering.
Regenerating adds the next version; nothing is overwritten.
``advisor.gapplan.infra`` maps these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from advisor.gapplan.domain.plan import PlanStatus


@dataclass(slots=True)
class GapPlan:
    id: uuid.UUID
    owner_id: uuid.UUID
    # The Target (ADR 0022): one of the user's roles, and optionally one
    # opening in it. Plain ids: the target component owns what they mean.
    role_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    target_label: str
    version: int
    status: PlanStatus
    created_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    snapshot: dict[str, Any] | None = None
    gaps: tuple[dict[str, Any], ...] = ()
    projects: tuple[dict[str, Any], ...] = ()
    stepping_stones: tuple[dict[str, Any], ...] = ()
    model_id: str | None = None
    template_version: str | None = None
    drafted_at: datetime | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        role_id: uuid.UUID,
        job_posting_id: uuid.UUID | None,
        label: str,
        version: int,
        at: datetime,
    ) -> GapPlan:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            target_label=label[:400],
            version=version,
            status=PlanStatus.DRAFTING,
            created_at=at,
        )

    def drafted(
        self,
        *,
        snapshot: dict[str, Any],
        label: str,
        gaps: tuple[dict[str, Any], ...],
        projects: tuple[dict[str, Any], ...],
        stepping_stones: tuple[dict[str, Any], ...],
        model_id: str,
        template_version: str,
        at: datetime,
    ) -> None:
        self.snapshot = snapshot
        self.target_label = label[:400]
        self.gaps = gaps
        self.projects = projects
        self.stepping_stones = stepping_stones
        self.model_id = model_id
        self.template_version = template_version
        self.status = PlanStatus.READY
        self.drafted_at = at

    def failed(self, *, code: str, message: str) -> None:
        self.status = PlanStatus.FAILED
        self.error_code = code
        self.error_message = message


@dataclass(slots=True)
class Milestone:
    id: uuid.UUID
    owner_id: uuid.UUID
    plan_id: uuid.UUID
    position: int
    title: str
    time_window: str
    outcome: str


@dataclass(slots=True)
class Task:
    id: uuid.UUID
    owner_id: uuid.UUID
    plan_id: uuid.UUID
    milestone_id: uuid.UUID
    position: int
    text: str
    due: str
    closes: tuple[str, ...]
    done_at: datetime | None = None

    def mark(self, done: bool, *, at: datetime) -> None:
        """Ticking an already-done task keeps when it was first done."""
        self.done_at = (self.done_at or at) if done else None
