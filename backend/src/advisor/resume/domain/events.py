"""What the Resume Advisor tells the rest of the system, as domain facts.

``advisor.resume.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.resume.domain.content import VersionSource


@dataclass(frozen=True, slots=True)
class ResumeTailored:
    owner_id: uuid.UUID
    resume_id: uuid.UUID
    role_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ResumeVersionSaved:
    owner_id: uuid.UUID
    resume_id: uuid.UUID
    number: int
    source: VersionSource


ResumeEvent = ResumeTailored | ResumeVersionSaved
