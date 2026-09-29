"""Custom roles against a real database (ADR 0021): what is stored, what the
outbox carries, and that nobody else sees them."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from advisor.rolemap.domain import Role, RoleFilter, RoleOrigin
from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration


async def test_a_custom_role_round_trips_with_its_origin_company_and_jd(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyRoleMapUnitOfWork(database)
    jd = uuid.uuid4()
    async with uow.for_owner(account) as mine:
        created = await mine.roles.create(
            Role.custom(
                owner_id=account,
                title="Staff Engineer",
                company_name="Northwind",
                private_posting_id=jd,
            )
        )
        await mine.roles.create(Role(id=uuid.uuid4(), owner_id=account, name="Backend"))

    async with uow.for_owner(account) as mine:
        [custom] = await mine.roles.get_list(RoleFilter(origin=RoleOrigin.CUSTOM))
        assert custom == created
        assert (custom.origin, custom.company_name, custom.private_posting_id) == (
            RoleOrigin.CUSTOM,
            "Northwind",
            jd,
        )
        assert await mine.roles.get_count(RoleFilter(origin=RoleOrigin.RECOMMENDED)) == 1

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.roles.get(created.id) is None


async def test_adding_a_custom_role_reaches_the_outbox_with_its_company_only(
    database: Database, account: uuid.UUID
) -> None:
    from advisor.rolemap.domain import CustomRoleAdded

    uow = SqlAlchemyRoleMapUnitOfWork(database)
    role_id = uuid.uuid4()
    async with uow.for_owner(account) as mine:
        mine.record(CustomRoleAdded(owner_id=account, role_id=role_id, company_name="Northwind"))

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert [tuple(row) for row in rows.all()] == [
            ("CustomRoleAdded", {"role_id": str(role_id), "company_name": "Northwind"})
        ]
