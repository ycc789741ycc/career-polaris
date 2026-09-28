"""Evidence no longer carries a confidence.

``profile.evidence.confidence`` was a fixed number per connector and kind of
fact. Nothing read it: the analysis never saw it, and a dimension's confidence
is the model's judgement of how much evidence there is. It is dropped rather
than left to look meaningful.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the column never exists.

Downgrading restores the column, but not the values it held: every row gets
0.8, the middle of the range the connectors wrote.
"""

from __future__ import annotations

from alembic import op

revision: str = "0012_drop_evidence_confidence"
down_revision: str | None = "0011_run_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE profile.evidence DROP COLUMN IF EXISTS confidence")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE profile.evidence "
        "ADD COLUMN IF NOT EXISTS confidence double precision NOT NULL DEFAULT 0.8"
    )
