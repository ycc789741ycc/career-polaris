"""The profile at the HTTP edge: connectors, uploads and evidence on the wire.

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra, no queue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.profile import (
    ConnectionView,
    EvidenceSource,
    EvidenceView,
    ProfileSnapshot,
    ResumeFileView,
)
from advisor.profile.domain import EvidenceGranularity
from advisor.profile.domain.timeline import Position
from api import errors
from api.dependencies import current_user, get_container
from api.routes import profile as profile_api
from kernel.errors import NotFoundError
from kernel.paging import Page, paginate

EVIDENCE_ID = uuid.uuid4()
RESUME_ID = uuid.uuid4()
SYNCED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)

EVIDENCE = EvidenceView(
    id=EVIDENCE_ID,
    source=EvidenceSource.GITHUB,
    reference="kestrel/api#412",
    fact="12 merged pull requests on the billing service",
    observed_on=date(2026, 8, 30),
    confidence=0.9,
    granularity=EvidenceGranularity.SUMMARY,
    tally=12,
    subject="kestrel/api",
)


class FakeProfile:
    def __init__(self) -> None:
        self.deleted: list[uuid.UUID] = []

    async def delete_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        if resume_id != RESUME_ID:
            raise NotFoundError("resume not found", resume_id=str(resume_id))
        self.deleted.append(resume_id)

    async def connections(self, owner_id: uuid.UUID) -> list[ConnectionView]:
        return [
            ConnectionView(
                kind="github",
                account="maya",
                status="connected",
                last_synced_at=SYNCED,
                last_error=None,
            )
        ]

    async def resumes(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[ResumeFileView]:
        rows = [
            ResumeFileView(
                id=RESUME_ID,
                filename="maya.pdf",
                status="parsed",
                parse_error=None,
                uploaded_at=SYNCED,
            )
        ]
        return paginate(rows, page, page_size)

    async def evidence(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[EvidenceView]:
        return paginate([EVIDENCE], page, page_size)

    async def upload_resume(self, owner_id: uuid.UUID, **_: Any) -> ResumeFileView:
        return ResumeFileView(
            id=RESUME_ID,
            filename="maya.pdf",
            status="uploaded",
            parse_error=None,
            uploaded_at=SYNCED,
        )

    async def snapshot(self, owner_id: uuid.UUID) -> ProfileSnapshot:
        return ProfileSnapshot(
            version=7,
            evidence=(EVIDENCE,),
            positions=(Position("Engineer", "Kestrel", date(2022, 3, 1), None),),
            total_experience_months=54,
        )


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(profile_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def profile() -> FakeProfile:
    return FakeProfile()


@pytest.fixture
def client(queued: list[dict[str, Any]], profile: FakeProfile) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(profile_api.router)
    app.dependency_overrides[current_user] = lambda: uuid.uuid4()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(profile=profile)
    return TestClient(app)


def test_every_connector_is_listed_whether_or_not_it_is_connected(client: TestClient) -> None:
    rows = {row["kind"]: row for row in client.get("/connections").json()["items"]}

    assert rows["github"] == {
        "kind": "github",
        "connected": True,
        "account": "maya",
        "status": "connected",
        "last_synced_at": "2026-09-20T08:00:00+00:00",
        "last_error": None,
        "scopes": rows["github"]["scopes"],
    }
    assert rows["github"]["scopes"], "the consent copy says what is asked for"
    assert rows["jira"]["connected"] is False
    assert rows["jira"]["status"] == "disconnected"
    assert rows["jira"]["last_synced_at"] is None


def test_an_upload_is_queued_for_parsing_not_parsed_in_the_request(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    response = client.post("/resumes", files={"file": ("maya.pdf", b"%PDF-1.7", "application/pdf")})

    assert response.status_code == 202
    assert response.json() == {"id": str(RESUME_ID), "filename": "maya.pdf", "status": "parsing"}
    assert [c["name"] for c in queued] == ["profile.parse_resume"]


def test_uploaded_resumes_list_their_parse_state(client: TestClient) -> None:
    assert client.get("/resumes").json()["items"] == [
        {
            "id": str(RESUME_ID),
            "filename": "maya.pdf",
            "status": "parsed",
            "parse_error": None,
            "uploaded_at": "2026-09-20T08:00:00+00:00",
        }
    ]


def test_deleting_a_resume_answers_no_content(client: TestClient, profile: FakeProfile) -> None:
    response = client.delete(f"/resumes/{RESUME_ID}")

    assert response.status_code == 204
    assert profile.deleted == [RESUME_ID]


def test_deleting_a_resume_that_is_not_yours_is_not_found(client: TestClient) -> None:
    response = client.delete(f"/resumes/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_evidence_goes_out_with_dates_and_enums_as_strings(client: TestClient) -> None:
    assert client.get("/evidence").json()["items"] == [
        {
            "id": str(EVIDENCE_ID),
            "source": "github",
            "reference": "kestrel/api#412",
            "fact": "12 merged pull requests on the billing service",
            "observed_on": "2026-08-30",
            "confidence": 0.9,
            "granularity": "summary",
            "tally": 12,
            "subject": "kestrel/api",
        }
    ]


def test_the_profile_counts_evidence_and_lists_the_timeline(client: TestClient) -> None:
    assert client.get("/profile").json() == {
        "version": 7,
        "evidence_count": 1,
        "total_experience_months": 54,
        "positions": [
            {
                "title": "Engineer",
                "company": "Kestrel",
                "started_on": "2022-03-01",
                "ended_on": None,
            }
        ],
    }


def test_a_page_holds_its_slice_and_the_size_of_the_whole_list(client: TestClient) -> None:
    first = client.get("/connections", params={"page": 1, "page_size": 1}).json()
    second = client.get("/connections", params={"page": 2, "page_size": 1}).json()

    assert (first["page"], first["page_size"], first["total"]) == (1, 1, 2)
    assert (second["page"], second["page_size"], second["total"]) == (2, 1, 2)
    assert [r["kind"] for r in first["items"] + second["items"]] == ["github", "jira"]


def test_a_page_past_the_end_is_empty_but_still_counts(client: TestClient) -> None:
    body = client.get("/evidence", params={"page": 3, "page_size": 5}).json()
    assert body == {"items": [], "page": 3, "page_size": 5, "total": 1}


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        # Page 2 of the whole list does not exist.
        {"page": 2},
    ],
)
def test_paging_that_makes_no_sense_is_refused_in_the_envelope(
    client: TestClient, params: dict[str, int]
) -> None:
    response = client.get("/evidence", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
