"""Imports every ORM model so ``Base.metadata`` is complete.

Alembic and the integration-test harness both need one place that knows about
all of them. Nothing else should import this.
"""

from __future__ import annotations

# Importing a component registers its ORM models on Base.metadata. The models
# stay private to their component; this module never names one.
import advisor.assessment
import advisor.gapfill
import advisor.gapplan
import advisor.identity
import advisor.market
import advisor.profile
import advisor.resume
import advisor.rolemap
import advisor.target  # noqa: F401
from kernel.db.base import Base
from kernel.outbox.models import OutboxEvent  # noqa: F401

# Schemas, in the order they are created.
SCHEMAS = (
    "identity",
    "profile",
    "market",
    "market_user",
    "rolemap",
    "assessment",
    "target",
    "gapfill",
    "gapplan",
    "resume",
    "outbox",
)

# Every table with an owner_id, covered by row-level security.
#
# `outbox` is excluded on purpose. Its `owner_id` is a routing hint, not a
# tenancy boundary: the crawler writes rows with no owner at all (it must not
# know which users a market change affects), and the dispatcher has to read
# every row to fan them out. Tenancy there is enforced by the grants instead —
# the crawler role may only INSERT and SELECT on it.
#
# Listed referencing tables first, so deleting a user's rows in this order never
# trips a foreign key (``resume.resume`` names ``resume.custom_template``).
OWNER_ZONE_TABLES = tuple(
    table.fullname
    for table in reversed(Base.metadata.sorted_tables)
    if "owner_id" in table.columns and not table.fullname.startswith("outbox.")
)

# Shared zone: no owner_id, reachable by the crawler role.
SHARED_MARKET_TABLES = (
    "market.company",
    "market.crawl_source",
    "market.job_posting",
    "market.posting_embedding",
    "market.search_result",
)

# A component whose models stopped loading would otherwise vanish from
# migrations and from the RLS checks without a word.
_unregistered = set(SCHEMAS) - {table.schema for table in Base.metadata.tables.values()}
if _unregistered:
    raise RuntimeError(f"no ORM models registered for schemas: {sorted(_unregistered)}")

metadata = Base.metadata

__all__ = ["OWNER_ZONE_TABLES", "SCHEMAS", "SHARED_MARKET_TABLES", "Base", "metadata"]
