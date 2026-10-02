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
from wiring.queue import enqueue, queue_build

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

    if name == EventName.ROLE_MAP_BUILD_FINISHED and owner_id:
        # Fits are scored once per build, when it closes, whatever it changed
        # (ADR 0024). A successful analysis always builds the map (ADR 0020),
        # so its new scores reach the fits here too; AssessmentCompleted,
        # DimensionsChanged and RoleRequirementsChanged queue nothing.
        await enqueue("rolemap.compute_fits", owner_id=str(owner_id))
        return

    if name == EventName.ANALYSIS_FINISHED and owner_id:
        # Recorded as the run closed, so it no longer counts as running. A
        # successful analysis always builds the role map, its cost confirmed
        # with the analysis's (ADR 0020); a failed one still releases a build
        # that waited for it (ADR 0018). Either build first waits for the
        # market sources it reads (ADR 0027).
        requested = await deps.activity.build_after_analysis(
            owner_id, succeeded=event.payload.get("status") == "ready"
        )
        if requested is not None:
            await queue_build(owner_id, requested)
        return

    if name == EventName.GAP_ANSWERS_SUBMITTED and owner_id:
        # The Target's plan and résumé are written again from the new
        # evidence, each only if the user has one. Two jobs, so gapplan and
        # resume never import each other (ADR 0023).
        target = {
            "owner_id": str(owner_id),
            "role_id": event.payload["role_id"],
            "job_posting_id": event.payload.get("job_posting_id"),
        }
        await enqueue("gapplan.regenerate", **target)
        await enqueue("resume.regenerate", **target)
        return

    if name == EventName.CUSTOM_ROLE_ADDED:
        # A company named on a custom role seeds board discovery. Only the
        # company crosses over: the crawl source it may leave has no owner
        # (domain decision 25). The route already recorded the build.
        company_name = event.payload.get("company_name")
        if company_name:
            company_id = await deps.market.company_named(company_name)
            await enqueue(
                "market.discover_board", company_id=str(company_id), company_name=company_name
            )
        return

    if name == EventName.TARGET_LOCATIONS_CHANGED:
        # Builds nothing: a build spends the user's key, so it waits until
        # they ask. The role map says its locations changed (ADR 0027).
        return
