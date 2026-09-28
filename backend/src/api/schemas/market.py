"""Market's wire shapes: watched roles at companies and pasted JDs."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field

from advisor.market import (
    MAX_TARGET_LOCATION,
    MAX_TARGET_LOCATIONS,
    CompanySubscriptionView,
    MarketScopeView,
    PostingView,
)
from api.schemas.common import ApiModel, Page, RequestModel, Timestamp


class SubscriptionRequest(RequestModel):
    """A watch on one role at one company (domain decision 19)."""

    company_name: str = Field(min_length=1, max_length=255)
    role_title: str = Field(min_length=1, max_length=255)
    role_id: uuid.UUID | None = None
    # A careers page or JD link; it is where board discovery starts.
    url: str | None = Field(default=None, max_length=1024, pattern=r"^https?://\S+$")


class TargetLocationsRequest(RequestModel):
    """The user's whole set of target locations (domain decision 21). The
    market domain checks the cap again; this rejects an oversized body early."""

    locations: list[Annotated[str, Field(min_length=1, max_length=MAX_TARGET_LOCATION)]] = Field(
        max_length=MAX_TARGET_LOCATIONS
    )


class MarketScope(ApiModel):
    """The user's target locations and how many open postings they take in.
    With none chosen, the count is the platform's baseline."""

    target_locations: list[str]
    open_posting_count: int

    @classmethod
    def from_view(cls, view: MarketScopeView) -> MarketScope:
        return cls(
            target_locations=view.target_locations, open_posting_count=view.open_posting_count
        )


class JobDescriptionRequest(RequestModel):
    company_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    location: str | None = None
    description: str = Field(min_length=1)
    url: str | None = None


class Subscription(ApiModel):
    """A watch on one role at one company (domain decision 19)."""

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    role_title: str
    role_id: uuid.UUID | None
    url: str | None
    # `manual` means there is no supported job board, so the user sees
    # plainly that nothing updates automatically.
    coverage: str
    last_refreshed_at: Timestamp | None

    @classmethod
    def from_view(cls, s: CompanySubscriptionView) -> Subscription:
        return cls(
            id=s.id,
            company_id=s.company_id,
            company_name=s.company_name,
            role_title=s.role_title,
            role_id=s.role_id,
            url=s.url,
            coverage=str(s.coverage),
            last_refreshed_at=s.last_refreshed_at,
        )


class PastedJobDescription(ApiModel):
    """A pasted JD. It is private to its owner and never enters shared data."""

    id: uuid.UUID
    company_name: str
    title: str
    location: str | None
    visibility: str

    @classmethod
    def from_view(cls, posting: PostingView) -> PastedJobDescription:
        return cls(
            id=posting.id,
            company_name=posting.company_name,
            title=posting.title,
            location=posting.location,
            visibility=str(posting.visibility),
        )


class SubscriptionPage(Page[Subscription]):
    pass


class PastedJobDescriptionPage(Page[PastedJobDescription]):
    pass
