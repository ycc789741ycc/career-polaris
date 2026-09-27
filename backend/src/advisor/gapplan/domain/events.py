"""What the gap plan tells the rest of the system, as domain facts.

``advisor.gapplan.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanDrafted:
    owner_id: uuid.UUID
    plan_id: uuid.UUID
    target_kind: str
    version: int


GapPlanEvent = PlanDrafted
