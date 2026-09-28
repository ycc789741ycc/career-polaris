"""Activity's wire shapes: what background work is running (ADR 0018)."""

from __future__ import annotations

from typing import Literal

from advisor.activity import ActivityView, PendingView, RunStatusView
from advisor.assessment import AnalysisRunView
from advisor.rolemap import BuildRunView
from api.schemas.common import ApiModel, JobError, Timestamp

RunState = Literal["waiting", "running", "ready", "failed"]


class PendingWork(ApiModel):
    """One sync or parse still running: the source kind, or the file name."""

    label: str
    started_at: Timestamp

    @classmethod
    def from_view(cls, found: PendingView) -> PendingWork:
        return cls(label=found.label, started_at=found.started_at)


class RunStatus(ApiModel):
    """The newest analysis or role-map build. ``waiting`` is a build asked for
    during an analysis; it starts when the analysis finishes. A run that stopped
    responding reads as ``failed`` with the code ``stale``."""

    status: RunState
    started_at: Timestamp
    finished_at: Timestamp | None
    error: JobError | None

    @classmethod
    def from_view(cls, found: RunStatusView) -> RunStatus:
        return cls(
            status=_state(found.status),
            started_at=found.started_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
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
        return cls(
            status=_state(found.status),
            started_at=found.started_at or found.requested_at,
            finished_at=found.finished_at,
            error=JobError.of(found.error_code, found.error_message),
        )


class Activity(ApiModel):
    """Everything running for this user, which the shell polls while any of it
    is busy (ADR 0006, ADR 0018)."""

    syncing: list[PendingWork]
    parsing: list[PendingWork]
    analysis: RunStatus | None
    role_map: RunStatus | None

    @classmethod
    def from_view(cls, found: ActivityView) -> Activity:
        return cls(
            syncing=[PendingWork.from_view(p) for p in found.syncing],
            parsing=[PendingWork.from_view(p) for p in found.parsing],
            analysis=None if found.analysis is None else RunStatus.from_view(found.analysis),
            role_map=None if found.role_map is None else RunStatus.from_view(found.role_map),
        )


def _state(status: str) -> RunState:
    match status:
        case "waiting" | "running" | "ready" | "failed":
            return status
        case _:
            raise ValueError(f"unknown run status {status!r}")
