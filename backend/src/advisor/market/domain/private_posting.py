"""A JD the user pasted. Private to them, always: it lives where the crawler
cannot reach (domain decision 6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from advisor.market.domain.constants import MAX_COMPANY_NAME, MAX_LOCATION, MAX_TITLE
from advisor.market.domain.posting import canonical_key
from advisor.market.domain.words import clip


@dataclass(slots=True)
class PrivateJobPosting:
    """A JD the user pasted. Private to them, always."""

    id: uuid.UUID
    owner_id: uuid.UUID
    canonical_key: str
    company_name: str
    title: str
    location: str | None
    description: str
    url: str | None
    # A matching crawled posting, so the user gets its weekly updates. Nothing
    # flows back the other way.
    shared_posting_id: uuid.UUID | None
    vector: list[float] | None = field(default=None)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def pasted(
        cls,
        *,
        owner_id: uuid.UUID,
        company_name: str,
        title: str,
        location: str | None,
        description: str,
        url: str | None,
        shared_posting_id: uuid.UUID | None,
    ) -> PrivateJobPosting:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            canonical_key=canonical_key(company=company_name, title=title, location=location),
            company_name=clip(company_name.strip(), MAX_COMPANY_NAME),
            title=clip(title.strip(), MAX_TITLE),
            location=clip(location, MAX_LOCATION) if location is not None else None,
            description=description,
            url=url,
            shared_posting_id=shared_posting_id,
        )
