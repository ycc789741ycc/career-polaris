"""The ``worker`` deployable: queued jobs and the outbox dispatcher.

Three queues run in one process: ``ai`` (assessment, role naming, requirement
extraction, difficulty estimates, fits, gap plans, résumé writing), ``sync``
(connectors, resume parsing) and ``docs`` (résumé PDF export). Splitting them
is a deployment change, not a code change.
"""

from __future__ import annotations

import asyncio
import contextlib

from kernel.config import Unit, get_settings
from kernel.db import get_psycopg_dsn
from kernel.jobs import Queue
from kernel.logging import configure_logging, get_logger
from kernel.presence import Heartbeat
from wiring.container import container
from wiring.queue import queue
from worker.dispatcher import dispatch_pending

log = get_logger(__name__)

DISPATCH_INTERVAL_SECONDS = 2.0


async def _dispatch_loop() -> None:
    deps = container()
    while True:
        try:
            handled = await dispatch_pending(deps)
            if handled:
                log.info("outbox.dispatched", events=handled)
        except Exception:
            log.error("outbox.loop_error", exc_info=True)
        await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)


async def main() -> None:
    settings = get_settings()
    configure_logging(f"{settings.service_name}-worker", settings.log_level)
    # Missing configuration fails here, at startup, not at first use.
    settings.require_for(Unit.WORKER)
    app = queue()
    # Says the worker is up, so work queued while it was away reads as
    # waiting rather than lost (ADR 0052).
    heartbeat = Heartbeat(
        get_psycopg_dsn(settings.require_database_url()),
        Unit.WORKER,
        interval_seconds=settings.presence_heartbeat_seconds,
    )
    heartbeat.start()

    async with app.open_async():
        dispatcher = asyncio.create_task(_dispatch_loop())
        queues = [str(Queue.AI), str(Queue.SYNC), str(Queue.DOCS)]
        log.info("worker.started", queues=queues)
        try:
            await app.run_worker_async(queues=queues)
        finally:
            dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher
            heartbeat.stop()


if __name__ == "__main__":
    asyncio.run(main())
