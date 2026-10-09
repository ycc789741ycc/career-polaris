"""One Atlassian report waits per user, however often it is asked for (ADR 0061).

Connecting, every Jira sync and each report all ask for the next one; the
queueing lock in Procrastinate's own table is what keeps that to one chain.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from kernel.config import Settings
from kernel.db import Database
from wiring.queue import queue, queue_jira_report

pytestmark = pytest.mark.integration

_WAITING = text(
    "SELECT count(*) FROM procrastinate.procrastinate_jobs"
    " WHERE queueing_lock = :lock AND status = 'todo'"
)


async def _delete_reports(database: Database, owner_id: uuid.UUID) -> None:
    """Procrastinate's delete trigger names its tables unqualified, so the
    transaction takes the job schema's search path, as the job runner does."""
    async with database.shared() as session:
        await session.execute(text("SET LOCAL search_path TO procrastinate"))
        await session.execute(
            text("DELETE FROM procrastinate_jobs WHERE queueing_lock = :lock"),
            {"lock": f"profile.report_jira_account:{owner_id}"},
        )


@pytest.fixture
async def owner(database: Database, settings: Settings) -> AsyncIterator[uuid.UUID]:
    owner_id = uuid.uuid4()
    async with queue().open_async():
        yield owner_id
    await _delete_reports(database, owner_id)


async def test_asking_twice_leaves_one_report_waiting(database: Database, owner: uuid.UUID) -> None:
    await queue_jira_report(owner, seconds=3600)
    await queue_jira_report(owner, seconds=60)

    async with database.shared() as session:
        waiting = await session.scalar(_WAITING, {"lock": f"profile.report_jira_account:{owner}"})
    assert waiting == 1


async def test_each_user_has_a_chain_of_their_own(database: Database, owner: uuid.UUID) -> None:
    other = uuid.uuid4()
    await queue_jira_report(owner, seconds=3600)
    await queue_jira_report(other, seconds=3600)

    async with database.shared() as session:
        mine = await session.scalar(_WAITING, {"lock": f"profile.report_jira_account:{owner}"})
        theirs = await session.scalar(_WAITING, {"lock": f"profile.report_jira_account:{other}"})
    await _delete_reports(database, other)
    assert (mine, theirs) == (1, 1)
