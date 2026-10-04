"""Contact details become typed items, each drawn with its icon (ADR 0048).

Every saved version's ``content`` and every chat revision's stored
``proposal`` move from ``contact``, one free-text line, to ``contacts``,
``[{kind, value}]``: the line split on the separators résumés use and each
piece classified by its shape. The rule is copied here as it stood, so the
migration never depends on application code.

Row-level security is lifted for the rewrite, as the rows are every user's.
Downgrading joins the items back into one line with " · ".
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0042_resume_contacts"
down_revision: str | None = "0041_resume_fonts"
branch_labels = None
depends_on = None

_TABLES = (("resume.version", "content"), ("resume.revision", "proposal"))

_SEPARATORS = re.compile(r"\s*(?:·|\||,|;|\n|•)\s*")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^\+?[\d\s().\-]{7,}$")
_DOMAIN = re.compile(r"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", re.IGNORECASE)


def _kind(value: str) -> str:
    lowered = value.lower()
    if _EMAIL.match(value.removeprefix("mailto:")):
        return "email"
    if "github.com" in lowered:
        return "github"
    if "linkedin.com" in lowered:
        return "linkedin"
    if _PHONE.match(value) and sum(c.isdigit() for c in value) >= 7:
        return "phone"
    if _DOMAIN.match(value):
        return "website"
    return "location"


def to_items(line: str) -> list[dict[str, str]]:
    pieces = [p.strip() for p in _SEPARATORS.split(line or "") if p.strip()]
    return [{"kind": _kind(p), "value": p[:200]} for p in pieces[:8]]


def to_line(items: list[dict[str, Any]]) -> str:
    return " · ".join(str(i.get("value", "")) for i in items if i.get("value"))


def _rewrite(upgrading: bool) -> None:
    bind = op.get_bind()
    for table, column in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        key, other = ("contact", "contacts") if upgrading else ("contacts", "contact")
        rows = bind.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} ? :key"),  # noqa: S608
            {"key": key},
        ).all()
        for row_id, data in rows:
            data = dict(data)
            value = data.pop(key)
            data[other] = to_items(str(value)) if upgrading else to_line(list(value or []))
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = CAST(:data AS jsonb) WHERE id = :id"),  # noqa: S608
                {"data": json.dumps(data), "id": row_id},
            )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rewrite(upgrading=True)


def downgrade() -> None:
    _rewrite(upgrading=False)
