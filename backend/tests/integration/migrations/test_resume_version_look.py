"""Migration 0060 gives every version stored before it its résumé's look
(ADR 0079): the SQL it backfills with reads as the look the app keeps."""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from sqlalchemy import text

from advisor.resume import Options, OwnLook, Template, create_resume_service
from advisor.resume.domain import TemplateSpec, VersionLook
from advisor.target import TargetRef
from kernel.db import Database, get_psycopg_dsn

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20261031_0060_resume_version_look.py"
)


class Target:
    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> object:
        return type("Preview", (), {"label": "Staff Platform Engineer"})()


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0060", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("own_template", [False, True], ids=["built-in", "own"])
async def test_the_backfill_reads_a_resume_as_the_look_the_app_keeps(
    database: Database, account: uuid.UUID, own_template: bool
) -> None:
    service = create_resume_service(
        database,
        target=Target(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gapfill=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=None,  # type: ignore[arg-type]
        template_max=10,
    )
    mine = await service.create_template(account, name="Mine", spec=TemplateSpec().to_dict())
    resume = await service.request(
        account, TargetRef(str(uuid.uuid4())), template="organic", options=Options()
    )
    look = OwnLook(heading_font="Inter", bold_titles=True, body_pt=10.5, title_pt=12.0)
    await service.update_settings(
        account,
        resume.id,
        template=mine.id if own_template else Template.PLAIN,
        options=Options(metrics=False, trim=True),
        look=look,
    )

    async with database.for_user(account) as session:
        read = (
            await session.execute(
                text(f"SELECT {_load().LOOK_OF_RESUME} FROM resume.resume AS r WHERE r.id = :id"),
                {"id": resume.id},
            )
        ).scalar_one()

    assert VersionLook.from_dict(read) == VersionLook(
        template=None if own_template else Template.PLAIN,
        custom_template_id=uuid.UUID(mine.id) if own_template else None,
        own_look=look,
        trim=True,
    )


async def test_the_backfill_reaches_every_owners_versions_as_the_migrator(
    database: Database, account: uuid.UUID
) -> None:
    """The migrator owns the tables but row-level security is forced on them,
    and ``migrate`` sets no ``app.user_id``: the backfill must still see every
    owner's versions. Run, as ``migrate`` runs it, on a version with no look,
    and rolled back."""
    url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not url:
        pytest.fail("MIGRATOR_DATABASE_URL is missing; run through `make test-integration`.")
    service = create_resume_service(
        database,
        target=Target(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gapfill=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=None,  # type: ignore[arg-type]
        template_max=10,
    )
    resume = await service.request(
        account, TargetRef(str(uuid.uuid4())), template="organic", options=Options()
    )
    await service.update_settings(
        account,
        resume.id,
        template=Template.PLAIN,
        options=Options(trim=True),
        look=OwnLook(body_font="Lato"),
    )
    version_id = uuid.uuid4()

    with psycopg.connect(get_psycopg_dsn(url)) as connection:
        try:
            connection.execute("ALTER TABLE resume.version ALTER COLUMN look DROP NOT NULL")
            # Stored as the owner, as the app would have before migration 0060.
            connection.execute("SELECT set_config('app.user_id', %s, true)", (str(account),))
            connection.execute(
                "INSERT INTO resume.version"
                " (id, owner_id, resume_id, number, label, content, source, look)"
                " VALUES (%s, %s, %s, 1, 'v1', %s, 'manual', NULL)",
                (version_id, account, resume.id, json.dumps({})),
            )
            connection.execute("SELECT set_config('app.user_id', '', true)")

            _load().backfill(connection.execute)

            connection.execute("SELECT set_config('app.user_id', %s, true)", (str(account),))
            row = connection.execute(
                "SELECT look FROM resume.version WHERE id = %s", (version_id,)
            ).fetchone()
        finally:
            connection.rollback()

    assert row is not None and row[0] is not None
    assert VersionLook.from_dict(row[0]) == VersionLook(
        template=Template.PLAIN, own_look=OwnLook(body_font="Lato"), trim=True
    )
