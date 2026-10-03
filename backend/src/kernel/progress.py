"""How a short AI job reports where it is, and how it is stopped (ADR 0042).

An Advisor job — writing questions, drafting a gap plan, writing a résumé or a
section, scoring a posting of the user's own — records its stage on its row as
it passes it, and the shell reads every running one from ``GET /activity``.
While the model writes, the gateway reports how far the reply has got as a
``Progress``: the share of the template's expected output written so far,
capped below 1 until the reply is checked, and the call's estimated cost.

A job is cancelled by marking its row. The job looks before each model call,
from inside the progress callback, and before it saves; seeing the mark it
raises ``JobCancelledError``, which stops a streamed call where it is. A call
already sent is still charged, and the ledger records it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# A streamed reply's share of the writing stage never passes this until it
# has been checked: the last stretch is parsing and validating, not writing.
WRITING_CAP = 0.95

# The gateway reports a streamed reply's progress at most this often.
REPORT_EVERY_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class Progress:
    # How much of the expected output is written: 0 before the call, at most
    # ``WRITING_CAP`` while it streams.
    fraction: float
    estimated_cost_usd: Decimal


ProgressCallback = Callable[[Progress], Awaitable[None]]


class JobCancelledError(Exception):
    """The job's row was marked cancelled; stop before the next call or save.

    Deliberately not a ``DomainError``: a cancelled job is not a failure, and
    is not recorded as one."""


@dataclass(frozen=True, slots=True)
class RunningJobView:
    """One Advisor job still running, as ``GET /activity`` lists it."""

    # questions | gap_plan | resume | section | own_posting_evaluation
    kind: str
    id: str
    role_id: str | None
    job_posting_id: str | None
    private_job_posting_id: str | None
    label: str
    stage: str | None
    # 0 to 1, never going backwards.
    progress: float
    started_at: datetime
    estimated_cost_usd: Decimal | None


def get_stage_progress(
    shares: dict[str, tuple[float, float]], stage: str, fraction: float = 0.0
) -> float:
    """A job's progress at ``fraction`` of the way through ``stage``, from
    each stage's share of the job: ``(start, end)``, both 0 to 1. Pure."""
    start, end = shares[stage]
    return start + min(max(fraction, 0.0), 1.0) * (end - start)
