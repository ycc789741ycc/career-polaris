"""Target's wire shape: what a gap plan or a résumé is aimed at (ADR 0022).

A Target is a role on the user's role map and optionally one opening in it, or
a posting of the user's own (Phase 8): exactly one of ``role_id`` and
``private_job_posting_id``. Bodies and query strings carry the same three ids.
"""

from __future__ import annotations

import uuid
from typing import Self

from pydantic import model_validator

from advisor.target import TargetRef
from api.schemas.common import ApiModel, RequestModel


class TargetRefBody(ApiModel):
    """A role on the user's role map and optionally one opening in it, or a
    posting of the user's own."""

    role_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None = None
    private_job_posting_id: uuid.UUID | None = None

    @classmethod
    def from_ref(cls, ref: TargetRef) -> TargetRefBody:
        return cls(
            role_id=ref.role_uuid,
            job_posting_id=ref.opening_uuid,
            private_job_posting_id=ref.own_posting_uuid,
        )


class TargetFields(RequestModel):
    """A request aimed at a Target: a role and optionally one opening in it,
    or a posting of the user's own. Anything else is refused as invalid."""

    role_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None
    private_job_posting_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        if (self.role_id is None) == (self.private_job_posting_id is None):
            raise ValueError("a target is a role, or a posting of your own: exactly one")
        if self.job_posting_id is not None and self.role_id is None:
            raise ValueError("an opening is aimed at inside its role")
        return self

    def ref(self) -> TargetRef:
        return TargetRef.of(self.role_id, self.job_posting_id, self.private_job_posting_id)
