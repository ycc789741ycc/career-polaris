"""Target's wire shapes: what a gap plan or a résumé can aim at."""

from __future__ import annotations

import uuid
from typing import Literal

from advisor.target import TargetOptionView, TargetRef
from api.schemas.common import ApiModel, Page, Salary

TargetKindName = Literal["matchedPosting", "privatePosting"]


class TargetRefBody(ApiModel):
    kind: TargetKindName
    id: str

    @classmethod
    def from_ref(cls, ref: TargetRef) -> TargetRefBody:
        return cls(kind=str(ref.kind), id=ref.id)


class TargetOption(ApiModel):
    """One row of the "Plan a route to" / "Write for" pickers (domain decision 16)."""

    kind: TargetKindName
    id: uuid.UUID
    title: str
    role_name: str | None
    role_id: uuid.UUID | None
    company_name: str
    label: str
    fit: int | None
    salary: Salary | None
    # atsBoard / jsonLd / publicApi for a crawled opening, "pasted" for the
    # user's own JD.
    source_kind: str | None
    url: str | None

    @classmethod
    def from_view(cls, option: TargetOptionView) -> TargetOption:
        return cls(
            kind=str(option.kind),
            id=option.id,
            title=option.title,
            role_name=option.role_name,
            role_id=option.role_id,
            company_name=option.company_name,
            label=option.label,
            fit=option.fit,
            salary=Salary.of(option.salary),
            source_kind=option.source_kind,
            url=option.url,
        )


class TargetOptionPage(Page[TargetOption]):
    pass
