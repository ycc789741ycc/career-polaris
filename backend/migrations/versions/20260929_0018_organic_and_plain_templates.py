"""Résumés come in the prototype's two templates, Organic and Plain.

``warm`` is renamed ``organic``, which is the same look under the prototype's
name, and ``brief`` goes: a résumé on it moves to ``plain``, the other
evidence-first, one-page-friendly look. The check on ``resume.resume.template``
is rewritten to match.

Downgrading renames ``organic`` back to ``warm``; résumés moved off ``brief``
stay ``plain``.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision: str = "0018_organic_and_plain_templates"
down_revision: str | None = "0017_gap_fill"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.execute("ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_template")
    # FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user
    # policy; lift it for the data step.
    op.execute("ALTER TABLE resume.resume NO FORCE ROW LEVEL SECURITY")
    bind = op.get_bind()
    renamed = bind.execute(
        text("UPDATE resume.resume SET template = 'organic' WHERE template = 'warm'")
    ).rowcount
    moved = bind.execute(
        text("UPDATE resume.resume SET template = 'plain' WHERE template = 'brief'")
    ).rowcount
    op.execute("ALTER TABLE resume.resume FORCE ROW LEVEL SECURITY")
    log.info("Renamed %s résumé(s) to organic; moved %s off brief to plain", renamed, moved)
    op.execute(
        "ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_template "
        "CHECK (template IN ('organic', 'plain'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_template")
    op.execute("ALTER TABLE resume.resume NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE resume.resume SET template = 'warm' WHERE template = 'organic'")
    op.execute("ALTER TABLE resume.resume FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_template "
        "CHECK (template IN ('warm', 'plain', 'brief'))"
    )
