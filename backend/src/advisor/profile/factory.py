"""Builds the profile component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

import uuid

from advisor.profile.infra.account_report import AccountReporter
from advisor.profile.infra.connectors import Connector
from advisor.profile.infra.oauth import TokenRefresher
from advisor.profile.infra.unit_of_work import SqlAlchemyProfileUnitOfWork
from advisor.profile.service import ProfileService
from kernel.db import Database
from kernel.storage import ObjectStore


def create_profile_service(
    database: Database,
    *,
    object_store: ObjectStore,
    connectors: dict[str, Connector],
    token_refreshers: dict[str, TokenRefresher],
    resume_max_bytes: int,
    resume_max_pages: int,
    http_timeout_seconds: float,
    user_agent: str,
    account_reporter: AccountReporter | None = None,
    reporting_owner_id: uuid.UUID | None = None,
) -> ProfileService:
    return ProfileService(
        SqlAlchemyProfileUnitOfWork(database),
        object_store=object_store,
        connectors=connectors,
        token_refreshers=token_refreshers,
        account_reporter=account_reporter,
        reporting_owner_id=reporting_owner_id,
        resume_max_bytes=resume_max_bytes,
        resume_max_pages=resume_max_pages,
        http_timeout_seconds=http_timeout_seconds,
        user_agent=user_agent,
    )
