"""Queued and scheduled work, on Postgres.

The worker image runs three queues: ``ai`` (assessment, cluster naming,
requirement extraction, difficulty estimates, fits, gap plans, résumé writing),
``sync`` (connectors, resume parsing) and ``docs`` (résumé PDF export).
``notify`` arrives with the digest work. Splitting a queue into its own process group
later is a deployment change, not a code change
(docs/architecture.md section 1).
"""

from __future__ import annotations

from enum import StrEnum

from procrastinate import App, PsycopgConnector

from kernel.config import Settings
from kernel.db import get_psycopg_dsn


class Queue(StrEnum):
    AI = "ai"
    SYNC = "sync"
    DOCS = "docs"


# Procrastinate manages its own tables. They live in their own schema rather
# than `public`, which has no default grants in this database.
JOB_SCHEMA = "procrastinate"


def build_app(settings: Settings, *, url: str | None = None) -> App:
    return App(
        connector=PsycopgConnector(
            conninfo=get_psycopg_dsn(url or str(settings.database_url)),
            kwargs={"options": f"-c search_path={JOB_SCHEMA}"},
        ),
    )
