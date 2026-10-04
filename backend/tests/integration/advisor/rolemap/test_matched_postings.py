"""The role map's "Top matched" list, against a real database (ADR 0028).

What is worth proving: expired postings, retired roles and pasted JDs stay
out; the order follows the role's fit, or the posting date when asked for
the newest first; and the map counts, for each role, exactly the openings
this list can show for it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from advisor.identity import create_identity_service
from advisor.market import (
    NormalizedPosting,
    SourceKind,
    create_crawl_ingest,
    create_market_service,
)
from advisor.market.infra.models import CrawlSource
from advisor.rolemap import FitView, MatchOrder, create_rolemap_service
from advisor.rolemap.infra.models import Role, RoleMember
from kernel.ai_gateway import AiGateway
from kernel.config import Settings
from kernel.db import Database
from kernel.db.base import utcnow
from tests.integration.places import WINDOWS, store_target_locations

pytestmark = pytest.mark.integration


def _posting(
    title: str, company: str, market: str, posted_on: date = date(2026, 9, 1)
) -> NormalizedPosting:
    return NormalizedPosting(
        external_id=title,
        company_name=company,
        title=title,
        location=market,
        description=f"You will work on {title}.",
        url=f"https://boards.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=posted_on,
        salary=None,
    )


def _fit(role_id: uuid.UUID, score: int) -> FitView:
    return FitView(
        role_id=role_id,
        score=score,
        reasoning="",
        gaps=(),
        uncovered=(),
        model_id="stub",
        created_at=utcnow(),
    )


async def test_top_matched_lists_open_postings_in_live_roles_by_role_fit(
    database: Database,
    crawler_database: Database,
    settings: Settings,
    account: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = uuid.uuid4().hex[:8]
    market_name = f"Match market {tag}"
    northwind, kestrel = f"Northwind {tag}", f"Kestrel {tag}"

    async with crawler_database.shared() as session:
        row = CrawlSource(kind="greenhouse", endpoint=f"https://boards.test/{uuid.uuid4()}")
        session.add(row)
        await session.flush()
        source_id = row.id

    try:
        ingest = create_crawl_ingest(crawler_database)
        await ingest.record_crawl(
            source_id,
            [
                _posting(f"Backend A {tag}", northwind, market_name),
                _posting(f"Backend B {tag}", kestrel, market_name, date(2026, 9, 5)),
                _posting(f"Backend Gone {tag}", kestrel, market_name),
                _posting(f"Platform {tag}", kestrel, market_name),
                _posting(f"Retired {tag}", northwind, market_name),
            ],
        )
        # A later crawl no longer sees one of them: it expires.
        await ingest.record_crawl(
            source_id,
            [
                _posting(f"Backend A {tag}", northwind, market_name),
                _posting(f"Backend B {tag}", kestrel, market_name, date(2026, 9, 5)),
                _posting(f"Platform {tag}", kestrel, market_name),
                _posting(f"Retired {tag}", northwind, market_name),
            ],
        )
        async with database.shared() as session:
            found = await session.execute(
                text("SELECT title, id FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            ids: dict[str, uuid.UUID] = {title: posting_id for title, posting_id in found.all()}

        market = create_market_service(database, windows=WINDOWS)
        await store_target_locations(database, account, [market_name])

        backend, platform, retired = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with database.for_user(account) as session:
            session.add_all(
                [
                    Role(id=backend, owner_id=account, name="Senior Backend Engineer"),
                    Role(id=platform, owner_id=account, name="Staff Platform Engineer"),
                    Role(id=retired, owner_id=account, name="Old Role", retired_at=utcnow()),
                ]
            )
            await session.flush()
            members = [
                (backend, str(ids[f"Backend A {tag}"])),
                (backend, str(ids[f"Backend B {tag}"])),
                (backend, str(ids[f"Backend Gone {tag}"])),
                # A member left from a custom role's pasted JD, before ADR 0030.
                (backend, f"private:{uuid.uuid4()}"),
                (platform, str(ids[f"Platform {tag}"])),
                (retired, str(ids[f"Retired {tag}"])),
            ]
            session.add_all(
                RoleMember(owner_id=account, role_id=role_id, posting_key=key)
                for role_id, key in members
            )

        identity = create_identity_service(database, default_monthly_cap_usd=Decimal("20"))
        gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
        rolemap = create_rolemap_service(
            database,
            market=market,
            gateway=gateway,
            embedding_model=settings.embedding_model_name,
            top_k=settings.role_map_top_k,
            candidate_count=settings.role_candidate_count,
        )

        async def fits(owner_id: uuid.UUID) -> list[FitView]:
            return [_fit(backend, 80), _fit(platform, 91), _fit(retired, 99)]

        monkeypatch.setattr(rolemap, "fits", fits)

        matched = await rolemap.matched_postings(account, limit=10)

        # One opening per company: Kestrel's best is Platform (91), so its
        # Backend B gives way and Northwind's Backend A follows.
        assert [(m.title, m.fit) for m in matched] == [
            (f"Platform {tag}", 91),
            (f"Backend A {tag}", 80),
        ]
        assert [m.title for m in await rolemap.matched_postings(account, limit=1)] == [
            f"Platform {tag}"
        ]

        # The role map lists one role's openings newest first, each with the
        # day it was posted.
        newest = await rolemap.matched_postings(
            account, limit=None, role_id=backend, order=MatchOrder.NEWEST
        )
        assert [(m.title, m.posted_on) for m in newest] == [
            (f"Backend B {tag}", date(2026, 9, 5)),
            (f"Backend A {tag}", date(2026, 9, 1)),
        ]

        # The map draws the same roles, each counting the openings Top matched
        # can list for it: the expired posting and the pasted JD's member are
        # not counted, and the retired role is not drawn.
        drawn = {role.id: role.opening_count for role in await rolemap.map_roles(account)}
        assert drawn == {backend: 2, platform: 1}
        for role_id, count in drawn.items():
            listed = await rolemap.matched_postings(account, limit=None, role_id=role_id)
            assert len(listed) == count
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
            )
