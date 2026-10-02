"""One exchange in the revision chat (section 2.9)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Revision:
    """One exchange in the revision chat: the request, the reply, the edit."""

    id: uuid.UUID
    owner_id: uuid.UUID
    resume_id: uuid.UUID
    request: str
    reply: str
    proposal: dict[str, Any] | None
    model_id: str
    template_version: str
    created_at: datetime
    applied_version_id: uuid.UUID | None = None
