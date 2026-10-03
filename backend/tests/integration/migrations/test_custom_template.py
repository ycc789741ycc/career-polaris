"""Migration 0036's constraint: a résumé is set in a built-in template or in
one of the user's own, never both and never neither (ADR 0040)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from advisor.resume import Options, create_resume_service
from advisor.resume.domain import TemplateSpec
from advisor.target import TargetRef
from kernel.db import Database

pytestmark = pytest.mark.integration


class Target:
    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> object:
        return type("Preview", (), {"label": "Staff Platform Engineer"})()


@pytest.mark.parametrize(
    "assignment",
    ["custom_template_id = :template", "template = NULL"],
    ids=["both", "neither"],
)
async def test_a_resume_holds_exactly_one_template(
    database: Database, account: uuid.UUID, assignment: str
) -> None:
    service = create_resume_service(
        database,
        target=Target(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=None,  # type: ignore[arg-type]
        template_max=10,
    )
    mine = await service.create_template(account, name="Mine", spec=TemplateSpec().to_dict())
    resume = await service.request(
        account, TargetRef(str(uuid.uuid4())), template="organic", options=Options()
    )

    with pytest.raises(IntegrityError, match="ck_resume_look"):
        async with database.for_user(account) as session:
            await session.execute(
                text(f"UPDATE resume.resume SET {assignment} WHERE id = :id"),
                {"id": resume.id, "template": uuid.UUID(mine.id)},
            )
