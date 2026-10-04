"""Activity's wire shapes: what background work is running (ADR 0018)."""

from __future__ import annotations

from typing import Literal

from advisor.activity import ActivityView, PendingView, RunningJobView, RunStatusView
from advisor.assessment import AnalysisRunView
from advisor.rolemap import BuildRunView
from api.schemas.common import ApiModel, JobError, Timestamp
from api.schemas.target import TargetRefBody

RunState = Literal["waiting", "running", "ready", "failed"]
WaitingFor = Literal["analysis", "market"]


class PendingWork(ApiModel):
    """One sync or parse still running: the source kind, or the file name."""

    label: str
    started_at: Timestamp

    @classmethod
    def from_view(cls, found: PendingView) -> PendingWork:
        return cls(label=found.label, started_at=found.started_at)


class RunStatus(ApiModel):
    """The newest analysis or role-map build. A ``waiting`` build says what it
    waits for: an analysis that is running, or the market sources it reads,
    being fetched (ADR 0027). A run that stopped responding reads as
    ``failed`` with the code ``stale``."""

    status: RunState
    started_at: Timestamp
    finished_at: Timestamp | None
    error: JobError | None
    waiting_for: WaitingFor | None = None

    @classmethod
    def from_view(cls, found: RunStatusView) -> RunStatus:
        return cls(
            status=_state(found.status),
            started_at=found.started_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
            waiting_for=_waiting_for(found.waiting_for),
        )

    @classmethod
    def from_analysis(cls, found: AnalysisRunView) -> RunStatus:
        return cls(
            status=_state(found.status),
            started_at=found.started_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
        )

    @classmethod
    def from_build(cls, found: BuildRunView) -> RunStatus:
        waiting_for: WaitingFor | None = None
        if found.status == "waiting":
            waiting_for = "market" if found.is_waiting_for_market else "analysis"
        return cls(
            status=_state(found.status),
            started_at=found.started_at or found.requested_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
            waiting_for=waiting_for,
        )


AdvisorJobKind = Literal["questions", "gap_plan", "resume", "section", "own_posting_evaluation"]


class AdvisorJob(ApiModel):
    """One short AI job of the Advisor still running (ADR 0042): its Target,
    the stage it has reached and how far it is, 0 to 1, never going backwards.
    ``estimated_cost_usd`` is set once its call is priced, before it is sent."""

    kind: AdvisorJobKind
    id: str
    target: TargetRefBody
    label: str
    stage: str | None
    progress: float
    started_at: Timestamp
    estimated_cost_usd: str | None

    @classmethod
    def from_view(cls, job: RunningJobView) -> AdvisorJob:
        return cls.model_validate(
            {
                "kind": job.kind,
                "id": job.id,
                "target": {
                    "role_id": job.role_id,
                    "job_posting_id": job.job_posting_id,
                    "private_job_posting_id": job.private_job_posting_id,
                },
                "label": job.label,
                "stage": job.stage,
                "progress": round(job.progress, 3),
                "started_at": job.started_at,
                "estimated_cost_usd": (
                    str(job.estimated_cost_usd) if job.estimated_cost_usd is not None else None
                ),
            }
        )


class Processing(ApiModel):
    """Whether the machine that runs background work is up (ADR 0051, 0052).

    While the worker is away, work the user starts is queued and runs when it
    is back; nothing reads as lost meanwhile. While the crawler is away, a
    role map waiting for the market waits for it. ``*_seen_at`` is each one's
    last heartbeat, or null if it never sent one."""

    is_worker_online: bool
    is_crawler_online: bool
    worker_seen_at: Timestamp | None
    crawler_seen_at: Timestamp | None

    @classmethod
    def from_view(cls, found: ActivityView) -> Processing:
        presence = found.presence
        return cls(
            is_worker_online=presence.worker.is_online,
            is_crawler_online=presence.crawler.is_online,
            worker_seen_at=presence.worker.seen_at,
            crawler_seen_at=presence.crawler.seen_at,
        )


class Activity(ApiModel):
    """Everything running for this user, which the shell polls while any of it
    is busy (ADR 0006, ADR 0018)."""

    syncing: list[PendingWork]
    parsing: list[PendingWork]
    analysis: RunStatus | None
    role_map: RunStatus | None
    # The Advisor's jobs still running, oldest first (ADR 0042).
    advisor_jobs: list[AdvisorJob]
    processing: Processing

    @classmethod
    def from_view(
        cls, found: ActivityView, advisor_jobs: tuple[RunningJobView, ...] = ()
    ) -> Activity:
        return cls(
            syncing=[PendingWork.from_view(p) for p in found.syncing],
            parsing=[PendingWork.from_view(p) for p in found.parsing],
            analysis=None if found.analysis is None else RunStatus.from_view(found.analysis),
            role_map=None if found.role_map is None else RunStatus.from_view(found.role_map),
            advisor_jobs=[
                AdvisorJob.from_view(job)
                for job in sorted(advisor_jobs, key=lambda j: (j.started_at, j.id))
            ],
            processing=Processing.from_view(found),
        )


def _waiting_for(value: str | None) -> WaitingFor | None:
    match value:
        case "analysis" | "market" | None:
            return value
        case _:
            raise ValueError(f"unknown wait {value!r}")


def _state(status: str) -> RunState:
    match status:
        case "waiting" | "running" | "ready" | "failed":
            return status
        case _:
            raise ValueError(f"unknown run status {status!r}")
