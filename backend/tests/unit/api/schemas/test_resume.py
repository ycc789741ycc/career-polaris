"""A tailored résumé on the wire: built from the component's view, with the
content's nested shape checked against the contract."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from advisor.resume import (
    CoverageView,
    ExportView,
    Options,
    ResumeSummaryView,
    ResumeView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    RevisionView,
    Template,
    VersionView,
)
from advisor.resume.domain import Bullet
from advisor.resume.domain.content import VersionSource
from advisor.resume.service import EvidenceNote
from advisor.target import OutdatedReason, TargetRef
from api.schemas.resume import ResumeContent as ContentBody
from api.schemas.resume import ResumeExport, TailoredResume, revision_event
from tests.unit.advisor.resume.builders import make_content

AT = datetime(2026, 9, 23, 12, 30, tzinfo=UTC)
ROLE_ID = uuid.uuid4()
RESUME_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()
CONTENT = make_content(Bullet("Cut p99 by 40%", ("e1",)), name="Maya", summary="Short.")


def _view() -> ResumeView:
    version = VersionView(
        id=VERSION_ID,
        number=2,
        label="After chat",
        source=VersionSource.CHAT,
        model_id="claude-opus-5",
        created_at=AT,
    )
    return ResumeView(
        summary=ResumeSummaryView(
            id=RESUME_ID,
            target=TargetRef(str(ROLE_ID)),
            label="Staff Platform Engineer · Meridian Labs",
            status="ready",
            error_code=None,
            error_message=None,
            latest_version=2,
            created_at=AT,
            updated_at=AT,
        ),
        snapshot=None,
        coverage=(
            CoverageView(
                requirement="Runs Kubernetes in production",
                verdict="covered",
                dimension_key="infra",
                evidence=(EvidenceNote(id="e1", reference="PR #12", fact="Migrated to EKS"),),
            ),
        ),
        template=Template.PLAIN,
        options=Options(metrics=True, reorder=False, trim=True),
        version=version,
        content=CONTENT,
        evidence={"e1": EvidenceNote(id="e1", reference="PR #12", fact="Migrated to EKS")},
        versions=(version,),
        revisions=(
            RevisionView(
                id=uuid.uuid4(),
                request="Shorter",
                reply="Done",
                has_proposal=True,
                applied_version_id=VERSION_ID,
                created_at=AT,
            ),
        ),
    )


def test_a_tailored_resume_carries_its_summary_and_its_content() -> None:
    body = TailoredResume.from_resume(_view()).model_dump(mode="json")

    assert body["id"] == str(RESUME_ID)
    assert body["target"] == {
        "role_id": str(ROLE_ID),
        "job_posting_id": None,
        "private_job_posting_id": None,
    }
    assert body["status"] == "ready" and body["error"] is None
    assert body["template"] == "plain"
    assert body["options"] == {"metrics": True, "reorder": False, "trim": True}
    assert body["updated_at"] == "2026-09-23T12:30:00+00:00"
    # The coverage verdict's own dimension key stays inside the component.
    assert body["coverage"] == [
        {
            "requirement": "Runs Kubernetes in production",
            "verdict": "covered",
            "evidence": [{"id": "e1", "reference": "PR #12", "fact": "Migrated to EKS"}],
            "answers": [],
        }
    ]
    assert body["version"]["source"] == "chat"
    assert body["content"] == CONTENT.to_dict()
    assert body["evidence"] == {"e1": {"reference": "PR #12", "fact": "Migrated to EKS"}}
    assert body["revisions"][0]["applied_version_id"] == str(VERSION_ID)
    assert (body["is_outdated"], body["outdated_by"]) == (False, [])


def test_an_outdated_resume_says_what_moved_on() -> None:
    view = replace(_view(), outdated_by=(OutdatedReason.EVIDENCE, OutdatedReason.TARGET))
    body = TailoredResume.from_resume(view).model_dump(mode="json")

    assert (body["is_outdated"], body["outdated_by"]) == (True, ["evidence", "target"])


def test_a_version_rewritten_after_fill_the_gap_still_reads() -> None:
    """Nothing saves ``answers`` since ADR 0035; versions saved before keep it."""
    old = replace(_view().versions[0], source=VersionSource.ANSWERS)
    body = TailoredResume.from_resume(replace(_view(), version=old, versions=(old,)))

    assert body.version is not None and body.version.source == "answers"


def test_content_that_drifted_from_the_contract_is_refused() -> None:
    """The domain owns the content's shape; a field it grows unannounced is an
    error here rather than something the client silently ignores."""
    drifted = {**CONTENT.to_dict(), "photo_url": "https://example.test/me.jpg"}
    with pytest.raises(ValidationError):
        ContentBody.from_dict(drifted)


def test_a_failed_export_says_why() -> None:
    export = ExportView(
        id=uuid.uuid4(),
        version_id=VERSION_ID,
        template=Template.ORGANIC,
        status="failed",
        error_code="render_failed",
        error_message="the PDF could not be made",
        download_url=None,
    )
    body = ResumeExport.from_view(export).model_dump(mode="json")
    assert body["status"] == "failed"
    assert body["error"] == {"code": "render_failed", "message": "the PDF could not be made"}
    assert body["download_url"] is None


def test_each_chat_event_has_its_name_and_a_json_body() -> None:
    text = revision_event(RevisionText("Shorter, "))
    assert text["event"] == "text" and json.loads(text["data"]) == {"text": "Shorter, "}

    revision_id = uuid.uuid4()
    done = revision_event(RevisionDone(revision_id=revision_id, reply="Done", proposal=CONTENT))
    assert done["event"] == "proposal"
    assert json.loads(done["data"]) == {
        "revision_id": str(revision_id),
        "reply": "Done",
        "proposal": CONTENT.to_dict(),
    }

    failed = revision_event(RevisionFailed("ai_output_invalid", "rejected"))
    assert failed["event"] == "error"
    assert json.loads(failed["data"]) == {"code": "ai_output_invalid", "message": "rejected"}
