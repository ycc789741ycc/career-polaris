"""The Target picker at the HTTP edge: every option, in the client's terms.

Runs the real router in-process against a stand-in service — no network, no
infra.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.market import SalaryRange
from advisor.target import TargetKind, TargetOptionView
from api import errors
from api.dependencies import current_user, get_container
from api.routes.target import router

POSTING_ID = uuid.uuid4()
ROLE_ID = uuid.uuid4()


class FakeTargets:
    async def options(self, owner_id: uuid.UUID) -> list[TargetOptionView]:
        return [
            TargetOptionView(
                kind=TargetKind.MATCHED_POSTING,
                id=POSTING_ID,
                title="Staff Platform Engineer",
                role_name="Platform Engineer",
                role_id=ROLE_ID,
                company_name="Meridian Labs",
                fit=72,
                salary=SalaryRange(min_amount=180_000, max_amount=220_000, currency="USD"),
                source_kind="atsBoard",
                url="https://boards.example/meridian/1",
                subscription_id=None,
            )
        ]


def test_an_option_carries_its_kind_label_and_salary() -> None:
    app = FastAPI()
    errors.install(app)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: uuid.uuid4()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(target=FakeTargets())

    assert TestClient(app).get("/targets").json()["items"] == [
        {
            "kind": "matchedPosting",
            "id": str(POSTING_ID),
            "title": "Staff Platform Engineer",
            "role_name": "Platform Engineer",
            "role_id": str(ROLE_ID),
            "company_name": "Meridian Labs",
            "label": "Platform Engineer · Meridian Labs",
            "fit": 72,
            "salary": {"min": 180_000, "max": 220_000, "currency": "USD"},
            "source_kind": "atsBoard",
            "url": "https://boards.example/meridian/1",
            "subscription_id": None,
        }
    ]
