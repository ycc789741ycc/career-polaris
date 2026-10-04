"""Migration 0039 gives every stored résumé every section, shown or hidden,
and takes the hidden ones away again (ADR 0043).

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

from advisor.resume.domain import (
    BUILT_IN_KINDS,
    ResumeContent,
    SectionSlot,
    assert_well_formed,
)
from kernel.db import Database

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20261012_0039_resume_all_sections.py"
)

_CITED = {"text": "Owned the retry layer", "evidence_ids": ["e1"], "origin": "written"}
OLD_SECTIONS = [
    {
        "kind": "experience",
        "title": None,
        "text": "",
        "entries": [
            {"title": "Engineer", "org": "Kestrel", "when": "2022", "link": "", "bullets": [_CITED]}
        ],
        "items": [],
        "bullets": [],
    },
    {"kind": "skills", "title": None, "text": "", "entries": [], "items": ["Go"], "bullets": []},
    {
        "kind": "custom",
        "title": "Volunteering",
        "text": "",
        "entries": [],
        "items": [],
        "bullets": [_CITED],
    },
]
OLD_PLAN = [
    {"kind": "experience", "title": None},
    {"kind": "skills", "title": None},
    {"kind": "custom", "title": "Volunteering"},
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0039", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rewrite(database: Database, expression: str, value: Any) -> Any:
    async with database.shared() as session:
        rows = await session.execute(
            text(f"SELECT {expression} FROM (SELECT CAST(:value AS jsonb) AS c) AS t"),
            {"value": json.dumps(value)},
        )
        return rows.scalar_one()


async def test_a_stored_resume_holds_every_section_and_gives_the_hidden_ones_back(
    database: Database,
) -> None:
    migration = _load()

    sections = await _rewrite(database, migration._held("c", empty_section=True), OLD_SECTIONS)

    content = ResumeContent.from_dict(
        {"name": "Maya", "headline": "", "contact": "", "sections": sections}
    )
    assert_well_formed(content)
    assert [s.is_shown for s in content.sections[:3]] == [True, True, True]
    assert {s.kind for s in content.sections} >= set(BUILT_IN_KINDS)
    added = content.sections[3:]
    assert all(not s.is_shown and s.is_empty for s in added)
    assert [str(s.kind) for s in added] == [
        "summary",
        "side_projects",
        "open_source",
        "education",
        "talks_and_writing",
        "certifications",
    ]

    downgraded = await _rewrite(database, migration._shown_only("c"), sections)

    assert downgraded == OLD_SECTIONS


async def test_a_stored_plan_holds_every_section_and_the_new_default_is_valid(
    database: Database,
) -> None:
    migration = _load()

    plan = await _rewrite(database, migration._held("c", empty_section=False), OLD_PLAN)

    slots = [SectionSlot.from_dict(s) for s in plan]
    assert [s.is_shown for s in slots] == [True, True, True, *([False] * 6)]
    assert await _rewrite(database, migration._shown_only("c"), plan) == OLD_PLAN
    default = await _rewrite(database, migration._NEW_DEFAULT.removesuffix("::jsonb"), {})
    assert [SectionSlot.from_dict(s).is_shown for s in json.loads(default)][:3] == [True] * 3
