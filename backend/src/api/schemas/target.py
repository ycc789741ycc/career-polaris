"""Target's wire shape: what a gap plan or a résumé is aimed at (ADR 0022)."""

from __future__ import annotations

import uuid

from advisor.target import TargetRef
from api.schemas.common import ApiModel


class TargetRefBody(ApiModel):
    """A role on the user's role map, and optionally one opening in it."""

    role_id: uuid.UUID
    job_posting_id: uuid.UUID | None = None

    @classmethod
    def from_ref(cls, ref: TargetRef) -> TargetRefBody:
        return cls(
            role_id=uuid.UUID(ref.role_id),
            job_posting_id=uuid.UUID(ref.job_posting_id) if ref.job_posting_id else None,
        )
