"""The Resume Advisor at the HTTP edge: queued, streamed, refused in the envelope.

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra, no queue.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.resume import (
    ExportView,
    Options,
    ResumeService,
    ResumeSummaryView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    SectionKind,
    SectionSlot,
    Template,
    TemplateReadingView,
)
from advisor.resume.domain import Bullet
from advisor.target import TargetRef
from api import errors
from api.dependencies import current_user, get_container
from api.routes import resume as resume_api
from kernel.errors import ConflictError, TargetUnusableError
from tests.unit.advisor.resume.builders import make_content
from tests.unit.advisor.resume.fakes import FakeResumeUnitOfWork

RESUME_ID = uuid.uuid4()
REVISION_ID = uuid.uuid4()
EXPORT_ID = uuid.uuid4()
READING_ID = uuid.uuid4()


class FakeResumes:
    def __init__(self) -> None:
        self.refuse = False
        self.export_status = "rendering"
        self.slots: list[SectionSlot] = []
        self.requested: list[tuple[TargetRef, Template, Options]] = []
        self.fail_revision = False

    async def request(
        self, owner_id: uuid.UUID, ref: TargetRef, *, template: Template, options: Options
    ) -> ResumeSummaryView:
        if self.refuse:
            raise TargetUnusableError("paste its job description instead")
        self.requested.append((ref, template, options))
        return ResumeSummaryView(
            id=RESUME_ID,
            target=ref,
            label="Staff Platform Engineer · Meridian Labs",
            status="drafting",
            error_code=None,
            error_message=None,
            latest_version=None,
            created_at=datetime(2026, 9, 23, tzinfo=UTC),
            updated_at=datetime(2026, 9, 23, tzinfo=UTC),
        )

    async def templates(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Any:
        # The real catalogue, over storage holding none of the user's own.
        service = ResumeService(
            FakeResumeUnitOfWork(),
            target=None,  # type: ignore[arg-type]
            profile=None,  # type: ignore[arg-type]
            assessment=None,  # type: ignore[arg-type]
            gateway=None,  # type: ignore[arg-type]
            object_store=None,  # type: ignore[arg-type]
        )
        return await service.templates(owner_id, page=page, page_size=page_size)

    async def upload_template_file(
        self, owner_id: uuid.UUID, *, content_type: str, content: bytes
    ) -> TemplateReadingView:
        return TemplateReadingView(
            id=READING_ID,
            status="reading",
            error_code=None,
            error_message=None,
            spec=None,
            read=(),
            defaulted=(),
            created_at=datetime(2026, 10, 10, tzinfo=UTC),
        )

    async def request_export(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, number: int
    ) -> ExportView:
        return ExportView(
            id=EXPORT_ID,
            version_id=uuid.uuid4(),
            template=Template.ORGANIC,
            status=self.export_status,
            error_code=None,
            error_message=None,
            download_url=None,
        )

    async def estimate_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> dict[str, Any]:
        self.slots.append(slot)
        return {
            "cost_usd": "0.02",
            "model_id": "claude-opus-5",
            "input_tokens": 900,
            "rate_is_published": True,
        }

    async def request_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> ResumeSummaryView:
        self.slots.append(slot)
        summary = await self.redraft(owner_id, resume_id)
        return replace(summary, status="filling")

    async def redraft(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> ResumeSummaryView:
        if self.refuse:
            raise ConflictError("this résumé is already being written")
        return ResumeSummaryView(
            id=resume_id,
            target=TargetRef(str(uuid.uuid4())),
            label="Staff Platform Engineer · Meridian Labs",
            status="drafting",
            error_code=None,
            error_message=None,
            latest_version=3,
            created_at=datetime(2026, 9, 23, tzinfo=UTC),
            updated_at=datetime(2026, 10, 3, tzinfo=UTC),
        )

    async def revise(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, request: str, content: dict[str, Any]
    ) -> AsyncIterator[object]:
        yield RevisionText("Shorter, ")
        yield RevisionText("and it leads with reliability.")
        if self.fail_revision:
            yield RevisionFailed("ai_output_invalid", "the proposed revision was rejected")
            return
        yield RevisionDone(
            revision_id=REVISION_ID,
            reply="Shorter, and it leads with reliability.",
            proposal=make_content(Bullet("x", ("e1",)), name="Maya", summary="Short."),
        )


@pytest.fixture
def resumes() -> FakeResumes:
    return FakeResumes()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    async def enqueue_later(name: str, *, seconds: int, **kwargs: Any) -> None:
        calls.append({"name": name, "seconds": seconds, **kwargs})

    monkeypatch.setattr(resume_api, "enqueue", enqueue)
    monkeypatch.setattr(resume_api, "enqueue_later", enqueue_later)
    return calls


@pytest.fixture
def client(resumes: FakeResumes, queued: list[dict[str, Any]]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(resume_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(resume=resumes)
    return TestClient(app, raise_server_exceptions=False)


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into (event, data) pairs."""
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_writing_a_resume_queues_it_with_its_template_and_options(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    target = str(uuid.uuid4())
    response = client.post(
        "/tailored-resumes",
        json={
            "role_id": target,
            "template": "plain",
            "options": {"trim": True},
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "drafting"
    [(ref, template, options)] = resumes.requested
    assert (ref, template) == (TargetRef(target), Template.PLAIN)
    assert options == Options(metrics=True, reorder=True, trim=True)
    assert [(job["name"], job["resume_id"]) for job in queued] == [
        ("resume.generate", str(RESUME_ID))
    ]


def test_a_target_that_cannot_be_written_for_is_refused_before_queueing(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    resumes.refuse = True
    body = {"role_id": str(uuid.uuid4()), "job_posting_id": str(uuid.uuid4())}
    response = client.post("/tailored-resumes", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "target_unusable"
    assert queued == []


def test_an_unknown_template_is_refused_in_the_envelope(client: TestClient) -> None:
    response = client.post(
        "/tailored-resumes",
        json={"role_id": str(uuid.uuid4()), "template": "neon"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_chat_streams_text_then_one_proposal(client: TestClient) -> None:
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions",
        json={"message": "Make the summary shorter", "content": {"name": "Maya"}},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _events(response.text)
    assert [name for name, _ in events] == ["text", "text", "proposal"]
    assert "".join(data["text"] for name, data in events if name == "text") == (
        "Shorter, and it leads with reliability."
    )
    proposal = events[-1][1]
    assert proposal["revision_id"] == str(REVISION_ID)
    assert proposal["proposal"]["sections"][0] == {
        "kind": "summary",
        "title": None,
        "text": "Short.",
        "entries": [],
        "items": [],
        "bullets": [],
    }


def test_a_rejected_revision_ends_the_stream_with_a_coded_error(
    client: TestClient, resumes: FakeResumes
) -> None:
    resumes.fail_revision = True
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions",
        json={"message": "Invent a promotion", "content": {"name": "Maya"}},
    )
    events = _events(response.text)
    assert events[-1] == (
        "error",
        {"code": "ai_output_invalid", "message": "the proposed revision was rejected"},
    )
    assert "proposal" not in [name for name, _ in events]


def test_an_empty_chat_message_is_refused(client: TestClient) -> None:
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions", json={"message": "", "content": {}}
    )
    assert response.status_code == 422


def test_regenerating_queues_the_next_version_when_asked(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    response = client.post(f"/tailored-resumes/{RESUME_ID}/regenerate")

    assert response.status_code == 202
    assert response.json()["status"] == "drafting"
    assert [(job["name"], job["resume_id"]) for job in queued] == [
        ("resume.generate", str(RESUME_ID))
    ]


def test_regenerating_while_it_is_written_is_refused_before_queueing(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    resumes.refuse = True
    response = client.post(f"/tailored-resumes/{RESUME_ID}/regenerate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert queued == []


def test_every_template_is_served_as_the_renderer_draws_it(client: TestClient) -> None:
    body = client.get("/resume-templates").json()

    assert body["total"] == 2 and body["page"] == 1
    organic, plain = body["items"]
    assert organic["id"] == "organic" and organic["is_built_in"]
    assert (organic["spec"]["heading_font"], organic["spec"]["body_font"]) == (
        "Caprasimo",
        "Figtree",
    )
    assert (organic["title_pt"], organic["contact_pt"], organic["small_pt"]) == (11.0, 9.5, 9.0)
    assert (organic["trimmed_bullets"], organic["trimmed_skills"]) == (3, 12)
    assert plain["rule"] == "1px solid #cfcac5"


def test_a_template_of_your_own_is_refused_in_the_envelope_when_it_is_markup(
    client: TestClient,
) -> None:
    spec = {
        "accent_color": "#c67139; } body { display: none",
        "name_color": "#8a4a20",
        "text_color": "#201e1d",
        "rule_color": "#c67139",
        "name_pt": 22,
        "heading_pt": 8.5,
        "body_pt": 9.5,
    }
    response = client.post("/resume-templates", json={"name": "Mine", "spec": spec})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize(
    ("status", "queued_names"), [("rendering", ["resume.export"]), ("ready", [])]
)
def test_an_export_is_queued_only_when_it_has_to_be_rendered(
    client: TestClient,
    resumes: FakeResumes,
    queued: list[dict[str, Any]],
    status: str,
    queued_names: list[str],
) -> None:
    resumes.export_status = status
    response = client.post(f"/tailored-resumes/{RESUME_ID}/exports", json={"version": 1})

    assert response.status_code == 202 and response.json()["status"] == status
    assert [job["name"] for job in queued] == queued_names


def test_a_section_is_priced_then_added_and_queued_to_be_filled(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    priced = client.get(f"/tailored-resumes/{RESUME_ID}/sections/estimate?kind=education")
    assert priced.status_code == 200 and priced.json()["cost_usd"] == "0.02"
    assert queued == []

    added = client.post(
        f"/tailored-resumes/{RESUME_ID}/sections", json={"kind": "custom", "title": "Volunteering"}
    )

    assert added.status_code == 202 and added.json()["status"] == "filling"
    assert resumes.slots == [
        SectionSlot(SectionKind.EDUCATION),
        SectionSlot(SectionKind.CUSTOM, "Volunteering"),
    ]
    [job] = queued
    assert (job["name"], job["kind"], job["title"]) == (
        "resume.fill_section",
        "custom",
        "Volunteering",
    )


def test_an_unknown_kind_of_section_is_refused(client: TestClient) -> None:
    response = client.post(f"/tailored-resumes/{RESUME_ID}/sections", json={"kind": "photo"})

    assert response.status_code == 422


def test_a_template_file_is_read_now_and_forgotten_a_day_later(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    files = {"file": ("someone.pdf", b"%PDF-1.4", "application/pdf")}
    response = client.post("/resume-templates/upload", files=files)

    assert response.status_code == 202
    assert response.json()["status"] == "reading"
    assert [(c["name"], c.get("seconds")) for c in queued] == [
        ("resume.read_template", None),
        ("resume.forget_template_reading", 86_400),
    ]
    assert {c["template_reading_id"] for c in queued} == {str(READING_ID)}
