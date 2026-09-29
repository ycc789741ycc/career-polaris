"""The outbox dispatcher.

Turns committed domain events into queued jobs. This is also where a market
event becomes user work: the crawler emits ``PostingsChanged`` about a company
or a market and knows nothing about users, so the fan-out happens here, where
user data is legitimately readable (docs/architecture.md section 2).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from advisor.assessment import QuestionRoundTrigger
from kernel.db.base import utcnow
from kernel.logging import get_logger
from kernel.outbox import EventName, OutboxEvent
from wiring.container import Container
from wiring.queue import enqueue

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

    if name == EventName.PROFILE_UPDATED and owner_id:
        # New evidence gets fresh follow-up questions, but not a re-analysis
        # (ADR 0012). An answer is skipped: its route already re-runs the
        # analysis, which opens its own round.
        if event.payload.get("source") == "self_reported":
            return
        round_id = await deps.assessment.request_questions(
            owner_id, trigger=QuestionRoundTrigger.EVIDENCE
        )
        if round_id is not None:
            await enqueue(
                "assessment.generate_questions", owner_id=str(owner_id), round_id=str(round_id)
            )
        return

    if name in (EventName.ASSESSMENT_COMPLETED, EventName.DIMENSIONS_CHANGED) and owner_id:
        await enqueue("assessment.compute_fits", owner_id=str(owner_id))
        return

    if name == EventName.ANALYSIS_FINISHED and owner_id:
        # Recorded as the run closed, so it no longer counts as running: a
        # role map that waited for it starts now, whether or not it succeeded
        # (ADR 0018).
        started = await deps.activity.release_waiting_builds(owner_id)
        if started is not None:
            await enqueue("rolemap.recluster", owner_id=str(owner_id), build_id=str(started.id))
        return

    if name == EventName.ROLE_COUNT_CHANGED:
        # The route that saved the new k already recorded and queued the
        # rebuild, so the page sees it at once (ADR 0018).
        return

    if name == EventName.ROLE_REQUIREMENTS_CHANGED and owner_id:
        await enqueue("assessment.compute_fits", owner_id=str(owner_id))
        return

    if name == EventName.TARGET_LOCATIONS_CHANGED and owner_id:
        # A new scope: a role map the user already has is rebuilt on it, with
        # ADR 0018's gating. Nothing is materialised for the locations yet —
        # there is no public job API adapter to crawl them with.
        rebuild = await deps.activity.rebuild_role_map(owner_id)
        if rebuild is not None and rebuild.should_queue:
            await enqueue(
                "rolemap.recluster", owner_id=str(owner_id), build_id=str(rebuild.build.id)
            )
        return

    if name == EventName.POSTINGS_CHANGED:
        for affected in await _users_affected_by(deps, event.payload):
            # Joins a build already under way, or waits for a running analysis.
            requested = await deps.activity.request_role_map(affected)
            if requested.should_queue:
                await enqueue(
                    "rolemap.recluster", owner_id=str(affected), build_id=str(requested.build.id)
                )
        return


async def _users_affected_by(deps: Container, payload: dict[str, Any]) -> list[uuid.UUID]:
    """Resolve a market change to the users whose target locations take it in.

    The crawler cannot do this — it has no grant on any user schema — which is
    the whole reason the fan-out lives in the worker.
    """
    return await deps.market.owners_affected_by(market=payload.get("market"))
