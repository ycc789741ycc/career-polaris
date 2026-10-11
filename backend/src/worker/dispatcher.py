"""The outbox dispatcher.

Turns committed domain events into queued jobs. Every event it handles is about
one user. The market moves nobody's role map on its own any more (ADR 0027):
a build is started by something the user did, and fetches what it needs.
"""

from __future__ import annotations

from sqlalchemy import select

from kernel.db.base import utcnow
from kernel.logging import get_logger
from kernel.outbox import EventName, OutboxEvent
from wiring.container import Container
from wiring.queue import queue_build

log = get_logger(__name__)

BATCH_SIZE = 100


async def dispatch_pending(deps: Container, *, limit: int = BATCH_SIZE) -> int:
    """Claim undispatched events and turn them into jobs.

    ``FOR UPDATE SKIP LOCKED`` means several dispatchers can run without
    handling the same row twice.
    """
    async with deps.database.shared() as session:
        rows = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None))
            .order_by(OutboxEvent.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(rows.scalars())
        for event in events:
            try:
                await _handle(deps, event)
            except Exception as exc:
                event.attempts += 1
                event.last_error = f"{exc.__class__.__name__}: {exc}"
                log.error(
                    "outbox.dispatch_failed",
                    event_name=event.name,
                    event_id=str(event.id),
                    attempts=event.attempts,
                )
                continue
            event.dispatched_at = utcnow()
    return len(events)


async def _handle(deps: Container, event: OutboxEvent) -> None:
    name = event.name
    owner_id = event.owner_id

    if name == EventName.SOURCE_SYNCED:
        # Deliberately does not start an analysis: the user asks for that
        # explicitly, and every sync would otherwise spend their money.
        return

    if name == EventName.PROFILE_UPDATED:
        # Nothing that spends: the strength report marks itself out of date
        # (ADR 0015). Evidence no longer opens questions — those come from a
        # Target's gaps, in Fill the gap (ADR 0023).
        return

    if name == EventName.ROLE_MAP_BUILD_FINISHED:
        # Queues nothing: a build scores its fits itself, before it is ready,
        # so a finished map does not move afterwards (ADR 0024). A failed or
        # cancelled one scores nothing, and the map says when it is behind
        # the strengths (ADR 0071). AssessmentCompleted, DimensionsChanged
        # and RoleRequirementsChanged queue nothing either.
        return

    if name == EventName.ANALYSIS_FINISHED and event.payload.get("status") == "cancelled":
        # The user stopped it (ADR 0072), and the build waiting for it with it:
        # there is nothing to release.
        return

    if name == EventName.ANALYSIS_FINISHED and owner_id:
        # Recorded as the run closed, so it no longer counts as running. It
        # builds nothing on its own: the user starts every build (ADR 0071).
        # A build they asked for during the analysis waited for it (ADR 0018)
        # and goes on now, first waiting for the market sources it reads
        # (ADR 0027).
        requested = await deps.activity.release_build_after_analysis(owner_id)
        if requested is not None:
            await queue_build(owner_id, requested)
        return

    if name == EventName.GAP_ANSWERS_SUBMITTED:
        # Rewrites nothing. The submit queued reading the answers into the
        # Target's fit itself, at the price the user confirmed (ADR 0077);
        # the plan and résumé say they are outdated by the new evidence, and
        # the user regenerates either at a price they confirm (ADR 0035).
        return

    if name == EventName.TARGET_LOCATIONS_CHANGED:
        # Builds nothing: a build spends the user's key, so it waits until
        # they ask. The role map says its locations changed (ADR 0027).
        return
