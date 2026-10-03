"""Migration 0035 moves stored résumés into sections and back (ADR 0039).

Its rewrite is SQL over JSON, so it runs here against Postgres on a literal
value: no stored row is read or changed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text

from advisor.resume.domain import ResumeContent, assert_well_formed
from kernel.db import Database

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20261008_0035_resume_sections.py"
)

OLD = {
    "name": "Maya Lin Chen",
    "headline": "Backend Engineer",
    "contact": "maya@example.com",
    "summary": "Builds payment systems.",
    "experience": [
        {
            "title": "Backend Engineer",
            "org": "Kestrel",
            "when": "2022 — now",
            "bullets": [
                {"text": "Owned the retry layer", "evidence_ids": ["e1"], "origin": "written"},
            ],
        },
        {"title": "Engineer", "org": "Acme", "when": "2019 — 2022", "bullets": []},
    ],
    "skills": ["Go", "Postgres"],
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0035", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rewrite(database: Database, expression: str, value: dict[str, Any]) -> Any:
    async with database.shared() as session:
        rows = await session.execute(
            text(f"SELECT {expression} FROM (SELECT CAST(:value AS jsonb) AS c) AS t"),
            {"value": json.dumps(value)},
        )
        return rows.scalar_one()


async def test_a_stored_resume_moves_into_sections_and_back(database: Database) -> None:
    migration = _load()

    upgraded = await _rewrite(database, migration._to_sections("c"), OLD)

    content = ResumeContent.from_dict(upgraded)
    assert_well_formed(content)
    assert [str(s.kind) for s in content.sections] == ["summary", "experience", "skills"]
    summary, experience, skills = content.sections
    assert summary.text == "Builds payment systems."
    assert [e.org for e in experience.entries] == ["Kestrel", "Acme"]
    assert experience.entries[0].bullets[0].evidence_ids == ("e1",)
    assert skills.items == ("Go", "Postgres")

    downgraded = await _rewrite(database, migration._from_sections("c"), upgraded)

    assert downgraded == OLD
