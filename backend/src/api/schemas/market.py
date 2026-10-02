"""Market's wire shapes: target locations and pasted JDs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from advisor.market import (
    MAX_TARGET_LOCATION,
    MAX_TARGET_LOCATIONS,
    MarketScopeView,
    TargetLocationOptionView,
)
from api.schemas.common import ApiModel, Page, RequestModel


class TargetLocationsRequest(RequestModel):
    """The user's whole set of target locations (domain decision 21). The
    market domain checks again that each is on the list and the cap holds
    (ADR 0026); this rejects an oversized body early."""

    locations: list[Annotated[str, Field(min_length=1, max_length=MAX_TARGET_LOCATION)]] = Field(
        max_length=MAX_TARGET_LOCATIONS
    )


class TargetLocationOption(ApiModel):
    """One place on the list: ``kind`` is "remote", "region" or "country". A
    region is matched by its member countries and never searched (ADR 0026)."""

    name: str
    kind: Literal["remote", "region", "country"]

    @classmethod
    def from_view(cls, view: TargetLocationOptionView) -> TargetLocationOption:
        return cls(name=view.name, kind=view.kind)


class TargetLocationOptionPage(Page[TargetLocationOption]):
    pass


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
