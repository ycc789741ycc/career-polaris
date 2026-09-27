"""What the profile tells the rest of the system, as domain facts.

``advisor.profile.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.profile.domain.evidence import EvidenceSource


@dataclass(frozen=True, slots=True)
class SourceSynced:
    owner_id: uuid.UUID
    kind: str
    evidence: int


@dataclass(frozen=True, slots=True)
class ProfileUpdated:
    """Evidence changed. This does not start an analysis — the user asks for
    that explicitly — but it does open a round of follow-up questions against
    the latest one (ADR 0012)."""

    owner_id: uuid.UUID
    source: EvidenceSource
    version: int
    count: int


ProfileEvent = SourceSynced | ProfileUpdated
