"""A posting of the user's own: the rules for a role filled in by hand and an
upload named after its file (ADR 0034). Pure, no storage."""

from __future__ import annotations

import uuid

import pytest

from advisor.target.domain import (
    OwnPostingError,
    PostingSource,
    PrivateJobPosting,
    get_placeholder_title,
    parse_requirement_lines,
)

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_requirement_lines_are_trimmed_and_blank_ones_dropped() -> None:
    assert parse_requirement_lines([" Leads design ", "", "  ", "Owns uptime"]) == (
        "Leads design",
        "Owns uptime",
    )
    assert parse_requirement_lines([]) == ()


@pytest.mark.parametrize("lines", [["r"] * 31, ["x" * 501]])
def test_requirement_lines_are_capped(lines: list[str]) -> None:
    with pytest.raises(OwnPostingError):
        parse_requirement_lines(lines)


@pytest.mark.parametrize(
    ("filename", "title"),
    [
        ("principal-engineer.pdf", "principal-engineer"),
        ("Staff Engineer.v2.docx", "Staff Engineer.v2"),
        ("README", "README"),
        (".pdf", "Job description"),
    ],
)
def test_an_untitled_upload_is_named_after_its_file(filename: str, title: str) -> None:
    assert get_placeholder_title(filename) == title


def test_a_role_filled_in_keeps_what_it_asks_for_one_per_line() -> None:
    posting = PrivateJobPosting.filled_in(
        owner_id=OWNER, title="Staff", company_name="", requirements=("A", "B")
    )

    assert posting.source is PostingSource.FILLED_IN
    assert (posting.job_description, posting.company_name) == ("- A\n- B", None)
    assert not posting.has_estimated_requirements and posting.is_read


def test_a_role_filled_in_with_nothing_listed_is_estimated() -> None:
    posting = PrivateJobPosting.filled_in(
        owner_id=OWNER, title="Platform Lead", company_name=None, requirements=["", " "]
    )

    assert posting.has_estimated_requirements and posting.job_description is None
    assert not posting.is_waiting_for_its_file


def _upload(title: str | None) -> PrivateJobPosting:
    return PrivateJobPosting.uploaded(
        owner_id=OWNER,
        title=title,
        company_name=None,
        filename="jd.pdf",
        content_type="application/pdf",
        storage_key="k",
    )


def test_an_untitled_upload_takes_the_name_of_its_job_once() -> None:
    posting = _upload("  ")
    assert (posting.title, posting.has_placeholder_title) == ("jd", True)

    posting.update_title("  ")
    assert posting.title == "jd"
    posting.update_title("Principal Engineer")
    posting.update_title("Something else")

    assert (posting.title, posting.has_placeholder_title) == ("Principal Engineer", False)


def test_an_upload_with_a_title_keeps_it() -> None:
    posting = _upload("Staff Engineer")
    posting.update_title("Principal Engineer")

    assert posting.title == "Staff Engineer" and posting.is_waiting_for_its_file


# -- a job in the background (ADR 0042) -------------------------------------------


def test_an_evaluation_records_stages_forward_and_is_cancelled_only_while_running() -> None:
    from datetime import UTC, datetime

    from advisor.target.domain import (
        EvaluationStage,
        OwnPostingError,
        PostingEvaluation,
        PostingEvaluationStatus,
    )

    at = datetime(2026, 10, 11, tzinfo=UTC)
    run = PostingEvaluation.requested(
        owner_id=uuid.uuid4(), private_job_posting_id=uuid.uuid4(), reads_requirements=True, at=at
    )
    run.update_stage(EvaluationStage.SCORING, progress=0.4)
    run.update_stage(EvaluationStage.SCORING, progress=0.1)
    assert (run.stage, run.progress) == (EvaluationStage.SCORING, 0.4)

    run.update_cancelled(at)
    assert run.status is PostingEvaluationStatus.CANCELLED and not run.is_running
    with pytest.raises(OwnPostingError):
        run.update_cancelled(at)
