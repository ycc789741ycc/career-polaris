"""An export records whether it was cut to one page (ADR 0038).

``resume.export`` gains ``trim``, read when Export is clicked, so the PDF is the
page previewed then, and an export of the same version, template and trim is
reused rather than rendered again. Nullable: exports already stored have none,
and are never reused. Idempotent, since the baseline migration builds tables
from the live ORM metadata. Downgrading drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0034_export_trim"
down_revision: str | None = "0033_draft_basis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE resume.export ADD COLUMN IF NOT EXISTS trim boolean")


def downgrade() -> None:
    op.execute("ALTER TABLE resume.export DROP COLUMN IF EXISTS trim")
