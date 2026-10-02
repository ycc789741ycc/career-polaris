"""The market is fetched only when a role-map build needs it (ADR 0027).

Shared zone (no user id):

* ``market.crawl_source.due_at``: set while a build waits for the source to be
  fetched. The crawler fetches only due sources.
* ``market.job_posting.thinned_at``: set when a posting nothing holds lost its
  description and embedding. The row stays for Targets and salary history.
* ``market.search_result``: each search's current result list, replaced by
  every fetch of it. A posting a search found counts only while it is on one.

Owner zone, under RLS:

* ``rolemap.build_run`` gains the sources a build reads and waits for, when it
  asked the market, the target locations it was built for, and how old its
  market was.
* ``rolemap.role_candidate.fit_estimate``: the local estimate that chose the
  ten.
* ``rolemap.candidate_strength``: the dimensions the estimate weighs, handed
  over with the candidates.

And the one cross-user read goes: the ``fanout_read`` policy on
``market_user.market_preference``. Nothing resolves a market change to users
any more.

Searches found before this have no result list, so they leave every scope
until a build needs them again. Written to be idempotent, since the baseline
migration builds tables from the live ORM metadata.

Downgrading drops the new columns and tables and restores the policy.
"""

from __future__ import annotations

from alembic import op

revision: str = "0022_market_on_demand"
down_revision: str | None = "0021_target_location_list"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_STRENGTH = "rolemap.candidate_strength"


def upgrade() -> None:
    op.execute("ALTER TABLE market.crawl_source ADD COLUMN IF NOT EXISTS due_at timestamptz")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_source_due_at ON market.crawl_source (due_at) "
        "WHERE due_at IS NOT NULL"
    )
    op.execute("ALTER TABLE market.job_posting ADD COLUMN IF NOT EXISTS thinned_at timestamptz")
    op.execute(
        "CREATE TABLE IF NOT EXISTS market.search_result ("
        " id uuid NOT NULL,"
        " crawl_source_id uuid NOT NULL,"
        " job_posting_id uuid NOT NULL,"
        " rank integer NOT NULL,"
        " fetched_at timestamptz NOT NULL,"
        " CONSTRAINT pk_search_result PRIMARY KEY (id),"
        " CONSTRAINT uq_search_result_source_id UNIQUE (crawl_source_id, job_posting_id),"
        " CONSTRAINT fk_search_result_crawl_source_id_crawl_source FOREIGN KEY"
        " (crawl_source_id) REFERENCES market.crawl_source (id) ON DELETE CASCADE,"
        " CONSTRAINT fk_search_result_job_posting_id_job_posting FOREIGN KEY"
        " (job_posting_id) REFERENCES market.job_posting (id) ON DELETE CASCADE"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_result_job_posting_id "
        "ON market.search_result (job_posting_id)"
    )
    op.execute("GRANT SELECT ON market.search_result TO app_rw")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON market.search_result TO crawler_rw")

    for column in ("needed_source_ids", "awaited_source_ids", "locations"):
        op.execute(
            f"ALTER TABLE rolemap.build_run ADD COLUMN IF NOT EXISTS {column} "
            "jsonb NOT NULL DEFAULT '[]'"
        )
    for column in ("awaited_since", "market_data_at"):
        op.execute(f"ALTER TABLE rolemap.build_run ADD COLUMN IF NOT EXISTS {column} timestamptz")
    op.execute(
        "ALTER TABLE rolemap.role_candidate ADD COLUMN IF NOT EXISTS fit_estimate double precision"
    )

    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_STRENGTH} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " dimension_key varchar(64) NOT NULL,"
        " name varchar(255) NOT NULL,"
        " read text NOT NULL,"
        " weight double precision NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_candidate_strength PRIMARY KEY (id),"
        " CONSTRAINT uq_candidate_strength_owner_id UNIQUE (owner_id, dimension_key)"
        ")"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_candidate_strength_owner_id ON {_STRENGTH} (owner_id)"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_STRENGTH} TO app_rw")
    op.execute(f"ALTER TABLE {_STRENGTH} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_STRENGTH} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_STRENGTH}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_STRENGTH} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )

    # Nothing reads target locations across users any more (ADR 0027).
    op.execute("DROP POLICY IF EXISTS fanout_read ON market_user.market_preference")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS fanout_read ON market_user.market_preference")
    op.execute(
        "CREATE POLICY fanout_read ON market_user.market_preference FOR SELECT "
        "USING (current_setting('app.fanout', true) = 'on')"
    )
    op.execute(f"DROP TABLE IF EXISTS {_STRENGTH}")
    op.execute("ALTER TABLE rolemap.role_candidate DROP COLUMN IF EXISTS fit_estimate")
    for column in (
        "needed_source_ids",
        "awaited_source_ids",
        "locations",
        "awaited_since",
        "market_data_at",
    ):
        op.execute(f"ALTER TABLE rolemap.build_run DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS market.search_result")
    op.execute("ALTER TABLE market.job_posting DROP COLUMN IF EXISTS thinned_at")
    op.execute("DROP INDEX IF EXISTS market.ix_crawl_source_due_at")
    op.execute("ALTER TABLE market.crawl_source DROP COLUMN IF EXISTS due_at")
