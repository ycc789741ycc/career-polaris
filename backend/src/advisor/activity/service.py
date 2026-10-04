"""What is running across the journey, and when the next stage may start.

Each component records its own background work: ``profile`` its syncs and
parses, ``assessment`` its analysis runs, ``rolemap`` its builds. This module
reads them together and holds the rules between the stages (ADR 0018):

* An analysis does not start while a source is still syncing or parsing: it
  would silently miss the evidence they are about to write.
* A role-map build asked for during an analysis waits, and starts when that
  analysis finishes.
* A build then waits for the market sources it reads to be fetched, and
  starts when they are or at its deadline (ADR 0027). That wait belongs to
  ``rolemap``, which asks ``market`` itself.

It sits above every component it reads, because ``rolemap`` sits below
``assessment`` and so cannot ask whether an analysis is running. It has no
tables of its own.

The worker and the crawler may run on a machine that is not always on
(ADR 0051). Work waits for them while they are away, so the limit past which
work reads as lost counts only the time they have been up (ADR 0052).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.activity.domain import STALE, Staleness
from advisor.assessment import AnalysisRunView, AssessmentService
from advisor.profile import PendingSourceView, ProfileService
from advisor.rolemap import BuildRequestView, BuildRunView, RoleMapService
from kernel.clock import utcnow
from kernel.errors import AnalysisRunningError, SourcesProcessingError
from kernel.logging import get_logger
from kernel.presence.view import PresenceView

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
    """The newest analysis or role-map build, as the page shows it.

    ``waiting_for`` says why a waiting build waits: "analysis" or "market".
    """

    status: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    waiting_for: str | None = None

    @property
    def is_busy(self) -> bool:
        return self.status in ("waiting", "running")


@dataclass(frozen=True, slots=True)
class ActivityView:
    syncing: tuple[PendingView, ...]
    parsing: tuple[PendingView, ...]
    analysis: RunStatusView | None
    role_map: RunStatusView | None
    # Whether the worker and the crawler are up: the same for every user.
    presence: PresenceView

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
        get_presence: Callable[[], Awaitable[PresenceView]],
        stale_after_seconds: int,
    ) -> None:
        self._profile = profile
        self._assessment = assessment
        self._rolemap = rolemap
        self._get_presence = get_presence
        self._staleness = Staleness(timedelta(seconds=stale_after_seconds))

    async def status(self, owner_id: uuid.UUID) -> ActivityView:
        """Everything running for this user. Only reads: work past the limit
        is reported as lost here, and closed when a stage is next asked for."""
        now = utcnow()
        presence = await self._get_presence()
        processing = await self._profile.processing(owner_id)
        analysis = await self._assessment.latest_run(owner_id)
        build = await self._rolemap.latest_build(owner_id)
        return ActivityView(
            syncing=self._live(processing.syncing, now, presence),
            parsing=self._live(processing.parsing, now, presence),
            analysis=(None if analysis is None else self._analysis_status(analysis, now, presence)),
            role_map=None if build is None else self._build_status(build, now, presence),
            presence=presence,
        )

    async def request_analysis(self, owner_id: uuid.UUID) -> AnalysisRunView:
        """Record an analysis the user asked for, or say why it cannot start.

        The caller queues the returned run.
        """
        now = utcnow()
        presence = await self._get_presence()
        processing = await self._profile.processing(owner_id)
        syncing = self._live(processing.syncing, now, presence)
        parsing = self._live(processing.parsing, now, presence)
        if syncing or parsing:
            raise SourcesProcessingError(
                "wait until your sources finish syncing and parsing before analysing",
                syncing=[p.label for p in syncing],
                parsing=[p.label for p in parsing],
            )
        if await self._analysis_running(owner_id, now, presence):
            raise AnalysisRunningError("an analysis is already running")
        return await self._assessment.request_run(owner_id)

    async def request_role_map(self, owner_id: uuid.UUID) -> BuildRequestView:
        """Record a role-map build, waiting if an analysis is running.

        The caller queues the build only when ``should_queue`` is set, so a
        build already under way is never queued twice, and schedules a check
        on the market only when ``should_await_market`` is set.
        """
        now = utcnow()
        presence = await self._get_presence()
        current = await self._rolemap.latest_build(owner_id)
        if current is not None and current.is_open and self._build_is_lost(current, now, presence):
            await self._rolemap.fail_build(owner_id, current.id, code=STALE, message=_LOST_BUILD)
        wait = await self._analysis_running(owner_id, now, presence)
        requested = await self._rolemap.request_build(owner_id, wait=wait)
        log.info(
            "activity.role_map_requested",
            build_id=str(requested.build.id),
            status=requested.build.status,
            queued=requested.should_queue,
        )
        return requested

    async def build_after_analysis(
        self, owner_id: uuid.UUID, *, succeeded: bool
    ) -> BuildRequestView | None:
        """An analysis finished: what became of the build that follows it.

        A successful analysis always builds the role map (domain decision 24):
        it releases a build that waited for it, or records a new one, or joins
        one already open. Either way the build first asks the market for what
        it reads (ADR 0027). A failed analysis only releases a build that
        waited for it (ADR 0018).
        """
        if not succeeded:
            return await self._rolemap.release_waiting(owner_id)
        return await self.request_role_map(owner_id)

    async def _analysis_running(
        self, owner_id: uuid.UUID, now: datetime, presence: PresenceView
    ) -> bool:
        """Whether an analysis is running. One past the limit is closed as lost,
        which releases whatever waited on it."""
        run = await self._assessment.latest_run(owner_id)
        if run is None or not run.is_running:
            return False
        if self._is_stale(run.started_at, now, presence):
            await self._assessment.fail_run(owner_id, run.id, code=STALE, message=_LOST_ANALYSIS)
            return False
        return True

    def _is_stale(self, started_at: datetime, now: datetime, presence: PresenceView) -> bool:
        """Work the worker runs: past the limit, counted while it is up."""
        return self._staleness.is_stale(
            started_at, now=now, online_since=presence.worker.online_since
        )

    def _live(
        self, pending: tuple[PendingSourceView, ...], now: datetime, presence: PresenceView
    ) -> tuple[PendingView, ...]:
        return tuple(
            PendingView(label=p.label, started_at=p.started_at)
            for p in pending
            if not self._is_stale(p.started_at, now, presence)
        )

    def _analysis_status(
        self, run: AnalysisRunView, now: datetime, presence: PresenceView
    ) -> RunStatusView:
        if run.is_running and self._is_stale(run.started_at, now, presence):
            return RunStatusView("failed", run.started_at, None, STALE, _LOST_ANALYSIS)
        return RunStatusView(
            run.status, run.started_at, run.finished_at, run.error_code, run.error_message
        )

    def _build_status(
        self, build: BuildRunView, now: datetime, presence: PresenceView
    ) -> RunStatusView:
        started = build.started_at or build.requested_at
        if build.is_open and self._build_is_lost(build, now, presence):
            return RunStatusView("failed", started, None, STALE, _LOST_BUILD)
        waiting_for = None
        if build.status == "waiting":
            waiting_for = "market" if build.is_waiting_for_market else "analysis"
        return RunStatusView(
            build.status,
            started,
            build.finished_at,
            build.error_code,
            build.error_message,
            waiting_for=waiting_for,
        )

    def _build_is_lost(self, build: BuildRunView, now: datetime, presence: PresenceView) -> bool:
        """Past the limit since it started; or, still waiting, since it asked
        the market, or since it was asked for while it waits on an analysis,
        which is itself lost by then.

        A build waiting for the market needs the crawler to fetch and the
        worker to check: it counts only while both are up."""
        since = build.started_at or build.awaited_since or build.requested_at
        if build.started_at is None and build.is_waiting_for_market:
            worker, crawler = presence.worker.online_since, presence.crawler.online_since
            both = None if worker is None or crawler is None else max(worker, crawler)
            return self._staleness.is_stale(since, now=now, online_since=both)
        return self._is_stale(since, now, presence)
