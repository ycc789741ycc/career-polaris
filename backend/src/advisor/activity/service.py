"""What is running across the journey, and when the next stage may start.

Each component records its own background work: ``profile`` its syncs and
parses, ``assessment`` its analysis runs, ``rolemap`` its builds. This module
reads them together and holds the rules between the stages (ADR 0018):

* An analysis does not start while a source is still syncing or parsing: it
  would silently miss the evidence they are about to write.
* A role-map build asked for during an analysis waits, and starts when that
  analysis finishes.

It sits above every component it reads, because ``rolemap`` sits below
``assessment`` and so cannot ask whether an analysis is running. It has no
tables of its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.activity.domain import STALE, Staleness
from advisor.assessment import AnalysisRunView, AssessmentService
from advisor.profile import PendingSourceView, ProfileService
from advisor.rolemap import BuildRequestView, BuildRunView, RoleMapService
from kernel.clock import utcnow
from kernel.errors import AnalysisRunningError, SourcesProcessingError
from kernel.logging import get_logger

__all__ = ["ActivityService", "ActivityView", "PendingView", "RunStatusView"]

log = get_logger(__name__)

_LOST_ANALYSIS = "This analysis stopped responding. Start it again."
_LOST_BUILD = "Building the role map stopped responding. Start it again."


@dataclass(frozen=True, slots=True)
class PendingView:
    """One sync or parse still running."""

    label: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RunStatusView:
    """The newest analysis or role-map build, as the page shows it."""

    status: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None

    @property
    def is_busy(self) -> bool:
        return self.status in ("waiting", "running")


@dataclass(frozen=True, slots=True)
class ActivityView:
    syncing: tuple[PendingView, ...]
    parsing: tuple[PendingView, ...]
    analysis: RunStatusView | None
    role_map: RunStatusView | None

    @property
    def is_processing_sources(self) -> bool:
        return bool(self.syncing or self.parsing)


class ActivityService:
    def __init__(
        self,
        *,
        profile: ProfileService,
        assessment: AssessmentService,
        rolemap: RoleMapService,
        stale_after_seconds: int,
    ) -> None:
        self._profile = profile
        self._assessment = assessment
        self._rolemap = rolemap
        self._staleness = Staleness(timedelta(seconds=stale_after_seconds))

    async def status(self, owner_id: uuid.UUID) -> ActivityView:
        """Everything running for this user. Only reads: work past the limit
        is reported as lost here, and closed when a stage is next asked for."""
        now = utcnow()
        processing = await self._profile.processing(owner_id)
        analysis = await self._assessment.latest_run(owner_id)
        build = await self._rolemap.latest_build(owner_id)
        return ActivityView(
            syncing=self._live(processing.syncing, now),
            parsing=self._live(processing.parsing, now),
            analysis=None if analysis is None else self._analysis_status(analysis, now),
            role_map=None if build is None else self._build_status(build, now),
        )

    async def request_analysis(self, owner_id: uuid.UUID) -> AnalysisRunView:
        """Record an analysis the user asked for, or say why it cannot start.

        The caller queues the returned run.
        """
        now = utcnow()
        processing = await self._profile.processing(owner_id)
        syncing = self._live(processing.syncing, now)
        parsing = self._live(processing.parsing, now)
        if syncing or parsing:
            raise SourcesProcessingError(
                "wait until your sources finish syncing and parsing before analysing",
                syncing=[p.label for p in syncing],
                parsing=[p.label for p in parsing],
            )
        if await self._analysis_running(owner_id, now):
            raise AnalysisRunningError("an analysis is already running")
        return await self._assessment.request_run(owner_id)

    async def request_reanalysis(self, owner_id: uuid.UUID) -> AnalysisRunView:
        """Record the analysis an answered question starts.

        Not gated: the answer is already stored as evidence, and a run already
        under way would not include it.
        """
        return await self._assessment.request_run(owner_id)

    async def request_role_map(self, owner_id: uuid.UUID) -> BuildRequestView:
        """Record a role-map build, waiting if an analysis is running.

        The caller queues the build only when ``should_queue`` is set, so a
        build already under way is never queued twice.
        """
        now = utcnow()
        current = await self._rolemap.latest_build(owner_id)
        if current is not None and current.is_open and self._build_is_lost(current, now):
            await self._rolemap.fail_build(owner_id, current.id, code=STALE, message=_LOST_BUILD)
        wait = await self._analysis_running(owner_id, now)
        requested = await self._rolemap.request_build(owner_id, wait=wait)
        log.info(
            "activity.role_map_requested",
            build_id=str(requested.build.id),
            status=requested.build.status,
            queued=requested.should_queue,
        )
        return requested

    async def release_waiting_builds(self, owner_id: uuid.UUID) -> BuildRunView | None:
        """An analysis finished: start the build that waited for it, if any.
        The caller queues it."""
        return await self._rolemap.start_waiting(owner_id)

    async def _analysis_running(self, owner_id: uuid.UUID, now: datetime) -> bool:
        """Whether an analysis is running. One past the limit is closed as lost,
        which releases whatever waited on it."""
        run = await self._assessment.latest_run(owner_id)
        if run is None or not run.is_running:
            return False
        if self._staleness.is_stale(run.started_at, now=now):
            await self._assessment.fail_run(owner_id, run.id, code=STALE, message=_LOST_ANALYSIS)
            return False
        return True

    def _live(
        self, pending: tuple[PendingSourceView, ...], now: datetime
    ) -> tuple[PendingView, ...]:
        return tuple(
            PendingView(label=p.label, started_at=p.started_at)
            for p in pending
            if not self._staleness.is_stale(p.started_at, now=now)
        )

    def _analysis_status(self, run: AnalysisRunView, now: datetime) -> RunStatusView:
        if run.is_running and self._staleness.is_stale(run.started_at, now=now):
            return RunStatusView("failed", run.started_at, None, STALE, _LOST_ANALYSIS)
        return RunStatusView(
            run.status, run.started_at, run.finished_at, run.error_code, run.error_message
        )

    def _build_status(self, build: BuildRunView, now: datetime) -> RunStatusView:
        started = build.started_at or build.requested_at
        if build.is_open and self._build_is_lost(build, now):
            return RunStatusView("failed", started, None, STALE, _LOST_BUILD)
        return RunStatusView(
            build.status, started, build.finished_at, build.error_code, build.error_message
        )

    def _build_is_lost(self, build: BuildRunView, now: datetime) -> bool:
        """Past the limit since it started, or since it was asked for if it is
        still waiting: an analysis it waits on is itself lost by then."""
        return self._staleness.is_stale(build.started_at or build.requested_at, now=now)
