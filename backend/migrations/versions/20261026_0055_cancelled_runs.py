"""An analysis or a role-map build can be cancelled (ADR 0072).

``assessment.analysis_run`` and ``rolemap.build_run`` gain the ``cancelled``
status: closed by the user, never a failure. Only the check constraints
change; no row is rewritten. Downgrading turns cancelled rows into failed ones
first, so the narrower check holds.
"""

from __future__ import annotations

from alembic import op

revision: str = "0055_cancelled_runs"
down_revision: str | None = "0054_build_skill_assessment"
branch_labels = None
depends_on = None


_ANALYSIS_CHECK = "ck_analysis_run_status"
_BUILD_CHECK = "ck_build_run_status"


def upgrade() -> None:
    op.execute(f"ALTER TABLE assessment.analysis_run DROP CONSTRAINT IF EXISTS {_ANALYSIS_CHECK}")
    op.execute(
        f"ALTER TABLE assessment.analysis_run ADD CONSTRAINT {_ANALYSIS_CHECK}"
        " CHECK (status IN ('running', 'ready', 'failed', 'cancelled'))"
    )
    op.execute(f"ALTER TABLE rolemap.build_run DROP CONSTRAINT IF EXISTS {_BUILD_CHECK}")
    op.execute(
        f"ALTER TABLE rolemap.build_run ADD CONSTRAINT {_BUILD_CHECK}"
        " CHECK (status IN ('waiting', 'running', 'ready', 'failed', 'cancelled'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE assessment.analysis_run NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE assessment.analysis_run SET status = 'failed', error_code = 'cancelled',"
        " error_message = 'Cancelled.' WHERE status = 'cancelled'"
    )
    op.execute("ALTER TABLE assessment.analysis_run FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rolemap.build_run NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE rolemap.build_run SET status = 'failed', error_code = 'cancelled',"
        " error_message = 'Cancelled.' WHERE status = 'cancelled'"
    )
    op.execute("ALTER TABLE rolemap.build_run FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE assessment.analysis_run DROP CONSTRAINT IF EXISTS {_ANALYSIS_CHECK}")
    op.execute(
        f"ALTER TABLE assessment.analysis_run ADD CONSTRAINT {_ANALYSIS_CHECK}"
        " CHECK (status IN ('running', 'ready', 'failed'))"
    )
    op.execute(f"ALTER TABLE rolemap.build_run DROP CONSTRAINT IF EXISTS {_BUILD_CHECK}")
    op.execute(
        f"ALTER TABLE rolemap.build_run ADD CONSTRAINT {_BUILD_CHECK}"
        " CHECK (status IN ('waiting', 'running', 'ready', 'failed'))"
    )
