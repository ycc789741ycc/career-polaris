"""Queue wiring.

Modules expose plain async functions in their ``jobs.py``; they are registered
as tasks here. That keeps Procrastinate out of the module boundary — a module
never imports the job runner, and swapping it is a change in this file only.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from procrastinate import App

from advisor.rolemap import BuildRequestView, MarketWait
from kernel.config import get_settings
from kernel.jobs import Queue, build_app
from kernel.logging import get_logger
from wiring.container import Container, container

log = get_logger(__name__)


@lru_cache(maxsize=1)
def queue() -> App:
    app = build_app(get_settings())
    _register(app)
    return app


async def enqueue(name: str, **kwargs: Any) -> None:
    """Defer a task by name, without importing the function that runs it."""
    await queue().configure_task(name=name).defer_async(**kwargs)


async def enqueue_later(name: str, *, seconds: int, **kwargs: Any) -> None:
    """Defer a task by name to run no sooner than ``seconds`` from now."""
    await queue().configure_task(name=name, schedule_in={"seconds": seconds}).defer_async(**kwargs)


async def queue_build(owner_id: uuid.UUID, requested: BuildRequestView) -> None:
    """Act on what asking for a role-map build did: queue it once it has
    started, or schedule the first check on the market sources it waits for
    (ADR 0027). Neither when it joined a build already open."""
    build_id = str(requested.build.id)
    if requested.should_queue:
        await enqueue("rolemap.recluster", owner_id=str(owner_id), build_id=build_id)
    elif requested.should_await_market:
        await enqueue_later(
            "rolemap.await_market",
            seconds=get_settings().crawl_due_poll_seconds,
            owner_id=str(owner_id),
            build_id=build_id,
        )


def _register(app: App) -> None:
    from advisor.assessment import jobs as assessment_jobs
    from advisor.gapfill import jobs as gapfill_jobs
    from advisor.gapplan import jobs as gapplan_jobs
    from advisor.profile import jobs as profile_jobs
    from advisor.resume import jobs as resume_jobs
    from advisor.rolemap import jobs as rolemap_jobs
    from advisor.target import jobs as target_jobs

    def deps() -> Container:
        return container()

    @app.task(name="profile.sync_connection", queue=str(Queue.SYNC))
    async def sync_connection(owner_id: str, kind: str) -> None:
        await profile_jobs.sync_connection(deps(), owner_id=owner_id, kind=kind)

    @app.task(name="profile.parse_resume", queue=str(Queue.SYNC))
    async def parse_resume(owner_id: str, resume_id: str) -> None:
        await profile_jobs.parse_resume(deps(), owner_id=owner_id, resume_id=resume_id)

    @app.task(name="rolemap.recluster", queue=str(Queue.AI))
    async def recluster(owner_id: str, build_id: str) -> None:
        await rolemap_jobs.recluster(deps(), owner_id=owner_id, build_id=build_id)

    @app.task(name="rolemap.await_market", queue=str(Queue.SYNC))
    async def await_market(owner_id: str, build_id: str) -> None:
        # Each waiting build checks on its own sources, as its owner: nothing
        # reads across users to find who a fetch was for (ADR 0027).
        found = await rolemap_jobs.await_market(deps(), owner_id=owner_id, build_id=build_id)
        if found is MarketWait.START:
            await enqueue("rolemap.recluster", owner_id=owner_id, build_id=build_id)
        elif found is MarketWait.WAIT:
            await enqueue_later(
                "rolemap.await_market",
                seconds=get_settings().crawl_due_poll_seconds,
                owner_id=owner_id,
                build_id=build_id,
            )

    @app.task(name="assessment.run", queue=str(Queue.AI))
    async def run_assessment(owner_id: str, run_id: str) -> None:
        await assessment_jobs.run(deps(), owner_id=owner_id, run_id=run_id)

    @app.task(name="rolemap.compute_fits", queue=str(Queue.AI))
    async def compute_fits(owner_id: str) -> None:
        await rolemap_jobs.compute_fits(deps(), owner_id=owner_id)

    @app.task(name="target.evaluate_own_posting", queue=str(Queue.AI))
    async def evaluate_own_posting(owner_id: str, evaluation_id: str) -> None:
        await target_jobs.evaluate_own_posting(
            deps(), owner_id=owner_id, evaluation_id=evaluation_id
        )

    @app.task(name="gapplan.draft", queue=str(Queue.AI))
    async def draft_plan(owner_id: str, plan_id: str) -> None:
        await gapplan_jobs.draft(deps(), owner_id=owner_id, plan_id=plan_id)

    @app.task(name="gapplan.regenerate", queue=str(Queue.AI))
    async def regenerate_plan(
        owner_id: str,
        role_id: str | None,
        job_posting_id: str | None,
        private_job_posting_id: str | None = None,
    ) -> None:
        await gapplan_jobs.regenerate(
            deps(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            private_job_posting_id=private_job_posting_id,
        )

    @app.task(name="gapfill.write", queue=str(Queue.AI))
    async def write_questions(owner_id: str, set_id: str) -> None:
        await gapfill_jobs.write(deps(), owner_id=owner_id, set_id=set_id)

    @app.task(name="resume.regenerate", queue=str(Queue.AI))
    async def regenerate_resume(
        owner_id: str,
        role_id: str | None,
        job_posting_id: str | None,
        private_job_posting_id: str | None = None,
    ) -> None:
        await resume_jobs.regenerate(
            deps(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            private_job_posting_id=private_job_posting_id,
        )

    @app.task(name="resume.generate", queue=str(Queue.AI))
    async def generate_resume(owner_id: str, resume_id: str) -> None:
        await resume_jobs.generate(deps(), owner_id=owner_id, resume_id=resume_id)

    @app.task(name="resume.export", queue=str(Queue.DOCS))
    async def export_resume(owner_id: str, export_id: str) -> None:
        await resume_jobs.export(deps(), owner_id=owner_id, export_id=export_id)
