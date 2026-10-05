"""The rules between the journey's stages (ADR 0018), against a real database:
what each stage records while it runs, who can see it, and how a role map
waits for an analysis."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from advisor.activity import ActivityService
from advisor.assessment import AssessmentService, create_assessment_service
from advisor.profile import ProfileService, create_profile_service
from advisor.profile.domain import ResumeFile, ResumeStatus, SourceConnection
from advisor.profile.infra.unit_of_work import SqlAlchemyProfileUnitOfWork
from advisor.rolemap import RoleMapService, create_rolemap_service
from kernel.clock import utcnow
from kernel.db import Database
from kernel.errors import SourcesProcessingError
from kernel.presence import PresenceView, UnitPresence
from tests.unit.advisor.rolemap.fakes import FakeMarket

pytestmark = pytest.mark.integration


class _Presence:
    """The worker and the crawler as these tests need them: up for a day,
    unless a test takes the worker away. A worker running against the same
    database must not decide what these tests see."""

    def __init__(self) -> None:
        self.worker_since: datetime | None = utcnow() - timedelta(days=1)

    async def __call__(self) -> PresenceView:
        up = UnitPresence(online_since=utcnow() - timedelta(days=1), seen_at=None)
        return PresenceView(
            worker=UnitPresence(online_since=self.worker_since, seen_at=None), crawler=up
        )


class _Services:
    def __init__(self, database: Database) -> None:
        self.presence = _Presence()
        self.profile: ProfileService = create_profile_service(
            database,
            object_store=None,  # type: ignore[arg-type]
            connectors={},
            resume_max_bytes=10_000,
            resume_max_pages=5,
            http_timeout_seconds=1,
            user_agent="test",
        )
        # The market as the role map sees it, with nothing due: these tests are
        # about the stages' rules, and the shared database's crawl sources must
        # not decide whether a build waits (ADR 0027).
        self.rolemap: RoleMapService = create_rolemap_service(
            database,
            market=FakeMarket(),  # type: ignore[arg-type]
            gateway=None,  # type: ignore[arg-type]
            embedding_model="test-model",
            top_k=10,
            candidate_count=10,
        )
        self.assessment: AssessmentService = create_assessment_service(
            database,
            profile=self.profile,
            rolemap=self.rolemap,
            gateway=None,  # type: ignore[arg-type]
            confidence_threshold=0.6,
            candidate_count=10,
        )
        self.activity = ActivityService(
            profile=self.profile,
            assessment=self.assessment,
            rolemap=self.rolemap,
            get_presence=self.presence,
            stale_after_seconds=900,
        )


@pytest.fixture
def services(database: Database) -> _Services:
    return _Services(database)


async def _uploaded_resume(database: Database, owner: uuid.UUID) -> None:
    async with SqlAlchemyProfileUnitOfWork(database).for_owner(owner) as mine:
        await mine.resumes.create(
            ResumeFile(
                id=uuid.uuid4(),
                owner_id=owner,
                filename="cv.pdf",
                storage_key=f"test/{owner}/cv",
                content_type="application/pdf",
                byte_size=10,
                status=ResumeStatus.UPLOADED,
            )
        )


async def test_an_analysis_waits_for_a_resume_still_parsing(
    database: Database, services: _Services, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    await _uploaded_resume(database, account)

    status = await services.activity.status(account)
    assert [p.label for p in status.parsing] == ["cv.pdf"]
    with pytest.raises(SourcesProcessingError):
        await services.activity.request_analysis(account)

    # Someone else's upload holds nobody else up.
    assert (await services.activity.status(other_account)).parsing == ()
    assert (await services.activity.request_analysis(other_account)).is_running


async def test_a_requested_sync_is_stored_as_running(
    database: Database, services: _Services, account: uuid.UUID
) -> None:
    async with SqlAlchemyProfileUnitOfWork(database).for_owner(account) as mine:
        await mine.connections.create(SourceConnection.new(owner_id=account, kind="github"))

    await services.profile.request_sync(account, "github")

    assert [p.label for p in (await services.activity.status(account)).syncing] == ["github"]


async def test_a_role_map_waits_for_the_analysis_and_starts_when_it_finishes(
    database: Database, services: _Services, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    run = await services.activity.request_analysis(account)

    requested = await services.activity.request_role_map(account)
    assert not requested.should_queue and requested.build.status == "waiting"
    assert (await services.activity.status(other_account)).role_map is None

    await services.assessment.fail_run(account, run.id, code="ai_budget_exceeded", message="spent")
    released = await services.activity.build_after_analysis(account, succeeded=False)

    assert released is not None and released.build.id == requested.build.id
    status = await services.activity.status(account)
    assert status.role_map is not None and status.role_map.status == "running"
    assert status.analysis is not None and status.analysis.error_code == "ai_budget_exceeded"

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert [tuple(row) for row in rows.all()] == [
            (
                "AnalysisFinished",
                {"run_id": str(run.id), "status": "failed", "error_code": "ai_budget_exceeded"},
            )
        ]


async def test_an_analysis_queued_while_the_worker_is_away_is_not_lost(
    database: Database, services: _Services, account: uuid.UUID
) -> None:
    """ADR 0052: the machine that runs the work is off. A run recorded a day
    ago still reads as running, and is lost only once the worker has been
    back past the limit."""
    run = await services.activity.request_analysis(account)
    async with database.for_user(account) as session:
        await session.execute(
            text(
                "UPDATE assessment.analysis_run SET started_at = now() - interval '1 day' "
                "WHERE id = :id"
            ),
            {"id": run.id},
        )
    services.presence.worker_since = None

    away = await services.activity.status(account)
    assert away.analysis is not None and away.analysis.status == "running"

    services.presence.worker_since = utcnow() - timedelta(hours=1)
    back = await services.activity.status(account)
    assert back.analysis is not None and back.analysis.error_code == "stale"
