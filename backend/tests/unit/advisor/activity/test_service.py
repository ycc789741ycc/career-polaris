"""The rules between the journey's stages (ADR 0018), over the real assessment
and role-map use cases on in-memory storage, with a stand-in profile."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from advisor.activity import ActivityService
from advisor.assessment import AssessmentService
from advisor.profile import PendingSourceView, SourceProcessingView
from advisor.rolemap import RoleMapService
from kernel.clock import utcnow
from kernel.errors import AnalysisRunningError, SourcesProcessingError
from tests.unit.advisor.assessment.fakes import FakeAssessmentUnitOfWork
from tests.unit.advisor.rolemap.fakes import FakeRoleMapUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
STALE_AFTER = 900


class FakeProfile:
    def __init__(self) -> None:
        self.syncing: list[PendingSourceView] = []
        self.parsing: list[PendingSourceView] = []

    async def processing(self, owner_id: uuid.UUID) -> SourceProcessingView:
        return SourceProcessingView(syncing=tuple(self.syncing), parsing=tuple(self.parsing))


class World:
    def __init__(self) -> None:
        self.profile = FakeProfile()
        self.assessments = FakeAssessmentUnitOfWork()
        self.rolemaps = FakeRoleMapUnitOfWork()
        self.assessment = AssessmentService(
            self.assessments,
            profile=None,  # type: ignore[arg-type]
            rolemap=None,  # type: ignore[arg-type]
            market=None,  # type: ignore[arg-type]
            gateway=None,  # type: ignore[arg-type]
            confidence_threshold=0.5,
        )
        self.rolemap = RoleMapService(
            self.rolemaps,
            market=None,  # type: ignore[arg-type]
            profile=None,  # type: ignore[arg-type]
            gateway=None,  # type: ignore[arg-type]
            embedding_model="test-model",
        )
        self.activity = ActivityService(
            profile=self.profile,  # type: ignore[arg-type]
            assessment=self.assessment,
            rolemap=self.rolemap,
            stale_after_seconds=STALE_AFTER,
        )

    def age_runs(self) -> None:
        """Make every recorded analysis look older than the limit."""
        for run in self.assessments.store.runs.values():
            run.started_at -= timedelta(seconds=STALE_AFTER + 1)

    def age_builds(self) -> None:
        for build in self.rolemaps.store.builds.values():
            build.requested_at -= timedelta(seconds=STALE_AFTER + 1)
            if build.started_at is not None:
                build.started_at -= timedelta(seconds=STALE_AFTER + 1)


def _pending(label: str, *, age: timedelta = timedelta()) -> PendingSourceView:
    return PendingSourceView(label=label, started_at=utcnow() - age)


@pytest.fixture
def world() -> World:
    return World()


# --- 02 waits for 01 -------------------------------------------------------


async def test_nothing_is_running_for_a_new_user(world: World) -> None:
    status = await world.activity.status(OWNER)

    assert (status.syncing, status.parsing, status.analysis, status.role_map) == (
        (),
        (),
        None,
        None,
    )


@pytest.mark.parametrize("stage", ["syncing", "parsing"])
async def test_an_analysis_is_refused_while_a_source_is_still_processing(
    world: World, stage: str
) -> None:
    getattr(world.profile, stage).append(_pending("github"))

    with pytest.raises(SourcesProcessingError):
        await world.activity.request_analysis(OWNER)

    assert await world.assessment.latest_run(OWNER) is None


async def test_an_analysis_is_refused_while_another_is_running(world: World) -> None:
    await world.activity.request_analysis(OWNER)

    with pytest.raises(AnalysisRunningError):
        await world.activity.request_analysis(OWNER)


async def test_an_analysis_starts_once_sources_are_done(world: World) -> None:
    run = await world.activity.request_analysis(OWNER)

    status = await world.activity.status(OWNER)
    assert run.is_running
    assert status.analysis is not None and status.analysis.status == "running"


async def test_a_source_that_stopped_responding_no_longer_blocks_an_analysis(
    world: World,
) -> None:
    world.profile.parsing.append(_pending("cv.pdf", age=timedelta(seconds=STALE_AFTER + 1)))

    assert (await world.activity.status(OWNER)).parsing == ()
    assert (await world.activity.request_analysis(OWNER)).is_running


async def test_a_lost_analysis_reads_as_failed_and_is_closed_when_the_next_is_asked_for(
    world: World,
) -> None:
    lost = await world.activity.request_analysis(OWNER)
    world.age_runs()

    status = await world.activity.status(OWNER)
    assert status.analysis is not None
    assert (status.analysis.status, status.analysis.error_code) == ("failed", "stale")

    fresh = await world.activity.request_analysis(OWNER)

    assert fresh.id != lost.id
    stored = world.assessments.store.runs[lost.id]
    assert (str(stored.status), stored.error_code) == ("failed", "stale")


async def test_an_answer_reruns_the_analysis_without_the_gate(world: World) -> None:
    world.profile.syncing.append(_pending("github"))

    assert (await world.activity.request_reanalysis(OWNER)).is_running


# --- 03 waits for 02 -------------------------------------------------------


async def test_a_role_map_runs_now_when_no_analysis_is_running(world: World) -> None:
    requested = await world.activity.request_role_map(OWNER)

    assert requested.should_queue and requested.build.status == "running"


async def test_a_role_map_waits_for_a_running_analysis_and_is_released_after(
    world: World,
) -> None:
    run = await world.activity.request_analysis(OWNER)

    requested = await world.activity.request_role_map(OWNER)
    assert not requested.should_queue and requested.build.status == "waiting"
    status = await world.activity.status(OWNER)
    assert status.role_map is not None and status.role_map.status == "waiting"

    await world.assessment.fail_run(OWNER, run.id, code="ai_budget_exceeded", message="spent")
    released = await world.activity.release_waiting_builds(OWNER)

    assert released is not None and released.id == requested.build.id
    assert released.status == "running"


async def test_a_role_map_does_not_wait_for_a_lost_analysis(world: World) -> None:
    await world.activity.request_analysis(OWNER)
    world.age_runs()

    requested = await world.activity.request_role_map(OWNER)

    assert requested.should_queue and requested.build.status == "running"


async def test_a_lost_build_is_closed_and_a_new_one_queued(world: World) -> None:
    lost = await world.activity.request_role_map(OWNER)
    world.age_builds()

    status = await world.activity.status(OWNER)
    assert status.role_map is not None
    assert (status.role_map.status, status.role_map.error_code) == ("failed", "stale")

    fresh = await world.activity.request_role_map(OWNER)

    assert fresh.should_queue and fresh.build.id != lost.build.id


# --- a new market scope ----------------------------------------------------


async def test_a_new_scope_builds_nothing_for_a_user_with_no_role_map(world: World) -> None:
    assert await world.activity.rebuild_role_map(OWNER) is None
    assert await world.rolemap.latest_build(OWNER) is None


async def test_a_new_scope_rebuilds_a_role_map_the_user_already_has(world: World) -> None:
    first = await world.activity.request_role_map(OWNER)
    await world.rolemap.fail_build(OWNER, first.build.id, code="internal", message="gone")

    rebuild = await world.activity.rebuild_role_map(OWNER)

    assert rebuild is not None and rebuild.should_queue
    assert rebuild.build.id != first.build.id
