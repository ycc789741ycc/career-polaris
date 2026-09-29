"""ORM rows to Fill the gap's entities and back. No rules live here, only shape."""

from __future__ import annotations

from typing import Any

from advisor.gapfill.domain import (
    AnswerType,
    AskedGap,
    GapQuestion,
    GapStatus,
    QuestionSet,
    QuestionSetStatus,
)
from advisor.gapfill.infra import models


def question_set(row: models.QuestionSet) -> QuestionSet:
    return QuestionSet(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        job_posting_id=row.job_posting_id,
        label=row.label,
        status=QuestionSetStatus(row.status),
        gaps=tuple(_gap(g) for g in row.gaps),
        created_at=row.created_at,
        model_id=row.model_id,
        template_version=row.template_version,
        error_code=row.error_code,
        error_message=row.error_message,
        written_at=row.written_at,
        submitted_at=row.submitted_at,
    )


def question_set_row(entity: QuestionSet) -> models.QuestionSet:
    row = models.QuestionSet(
        id=entity.id,
        owner_id=entity.owner_id,
        role_id=entity.role_id,
        job_posting_id=entity.job_posting_id,
        created_at=entity.created_at,
    )
    apply_question_set(row, entity)
    return row


def apply_question_set(row: models.QuestionSet, entity: QuestionSet) -> None:
    row.label = entity.label
    row.status = str(entity.status)
    row.gaps = [
        {"key": g.key, "label": g.label, "status": str(g.status), "lift": g.lift}
        for g in entity.gaps
    ]
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.written_at = entity.written_at
    row.submitted_at = entity.submitted_at


def question(row: models.Question) -> GapQuestion:
    return GapQuestion(
        id=row.id,
        owner_id=row.owner_id,
        set_id=row.set_id,
        position=row.position,
        gap_key=row.gap_key,
        gap_label=row.gap_label,
        gap_status=GapStatus(row.gap_status),
        lift=row.lift,
        text=row.text,
        asked_because=row.asked_because,
        answer_type=AnswerType(row.answer_type),
        choices=tuple(row.choices),
        evidence_id=row.evidence_id,
        answered_at=row.answered_at,
    )


def question_row(entity: GapQuestion) -> models.Question:
    row = models.Question(id=entity.id, owner_id=entity.owner_id, set_id=entity.set_id)
    apply_question(row, entity)
    return row


def apply_question(row: models.Question, entity: GapQuestion) -> None:
    row.position = entity.position
    row.gap_key = entity.gap_key
    row.gap_label = entity.gap_label
    row.gap_status = str(entity.gap_status)
    row.lift = entity.lift
    row.text = entity.text
    row.asked_because = entity.asked_because
    row.answer_type = str(entity.answer_type)
    row.choices = list(entity.choices)
    row.evidence_id = entity.evidence_id
    row.answered_at = entity.answered_at


def _gap(data: dict[str, Any]) -> AskedGap:
    return AskedGap(
        key=data["key"], label=data["label"], status=GapStatus(data["status"]), lift=data["lift"]
    )
