"""Searches of a public job API as crawl sources (ADR 0025).

* ``market.crawl_source.last_requested_at``: set on a search, when a user's
  candidates last asked for it. The crawler retires a search nobody has asked
  for in a while. It stays empty on a company's board, which is never retired
  for lack of demand.

Shared zone: no user id, and no policy to add. Written to be idempotent, since
the baseline migration builds tables from the live ORM metadata.

Downgrading drops the column. Search sources stay as rows the crawler has no
adapter for on the older code, where they fail each crawl and find nothing.
"""

from __future__ import annotations

from alembic import op

revision: str = "0020_search_sources"
down_revision: str | None = "0019_role_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE market.crawl_source ADD COLUMN IF NOT EXISTS last_requested_at timestamptz"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE market.crawl_source DROP COLUMN IF EXISTS last_requested_at")
