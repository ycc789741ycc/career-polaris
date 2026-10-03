"""A résumé template of the user's own (ADR 0040): a name and a checked spec,
kept per user."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from advisor.resume.domain.constants import MAX_TEMPLATE_NAME
from advisor.resume.domain.template_spec import TemplateSpec, TemplateSpecError, assert_spec_valid


@dataclass(slots=True)
class CustomTemplate:
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    spec: TemplateSpec
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls, *, owner_id: uuid.UUID, name: str, spec: TemplateSpec, at: datetime
    ) -> CustomTemplate:
        template = cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=_checked_name(name),
            spec=spec,
            created_at=at,
            updated_at=at,
        )
        assert_spec_valid(spec)
        return template

    def update_design(self, *, name: str, spec: TemplateSpec, at: datetime) -> None:
        assert_spec_valid(spec)
        self.name = _checked_name(name)
        self.spec = spec
        self.updated_at = at


def _checked_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise TemplateSpecError("a template needs a name")
    if len(cleaned) > MAX_TEMPLATE_NAME:
        raise TemplateSpecError(f"a template's name has at most {MAX_TEMPLATE_NAME} characters")
    return cleaned
