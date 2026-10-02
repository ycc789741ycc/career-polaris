"""The rules of Fill the gap (domain decision 27): which gaps are asked about,
what a written question must look like, and what counts as an answer.

Pure: no I/O, no framework, no kernel.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.gapfill.domain.constants import (
    MAX_ANSWER_CHARS,
    MAX_CHOICES,
    MAX_QUESTION_CHARS,
    MAX_QUESTIONS_PER_GAP,
    MIN_CHOICES,
)


class GapFillError(ValueError):
    """Questions or answers that break the rules of Fill the gap."""


class GapStatus(StrEnum):
    """How short of the Target the user is on a gap."""

    # A dimension the user scores below what the Target expects.
    PARTIAL = "partial"
    # A requirement nothing in the user's evidence speaks to.
    NO_EVIDENCE = "no_evidence"


class AnswerType(StrEnum):
    CHOICE = "choice"
    FREE_TEXT = "free_text"
    # A choice, with room to say more ("Which incident?").
    BOTH = "both"

    @property
    def has_choices(self) -> bool:
        return self is not AnswerType.FREE_TEXT


@dataclass(frozen=True, slots=True)
class AskedGap:
    """One gap of the Target, as the questions about it are written for it."""

    key: str
    label: str
    status: GapStatus
    # Fit points closing this gap alone is worth.
    lift: int


@dataclass(frozen=True, slots=True)
class DraftQuestion:
    """A question as the model wrote it, before it is stored."""

    gap_key: str
    text: str
    asked_because: str
    answer_type: AnswerType
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Answer:
    """What the user gave for one question: a choice, some text, or both."""

    question_id: uuid.UUID
    choice: str | None = None
    text: str | None = None


def assert_questions_valid(drafts: Sequence[DraftQuestion], gaps: Sequence[AskedGap]) -> None:
    """Every question is about a gap that was asked about, and answerable.

    A question about an unknown gap, one with no text or reason, a choice
    question without real choices, or too many questions for one gap is
    rejected: the model's output is untrusted, like any other.
    """
    known = {gap.key for gap in gaps}
    if not drafts:
        raise GapFillError("no questions were written")
    per_gap: dict[str, int] = {}
    for draft in drafts:
        if draft.gap_key not in known:
            raise GapFillError(f"a question is about a gap not asked about: {draft.gap_key}")
        if not draft.text.strip() or not draft.asked_because.strip():
            raise GapFillError("every question needs its text and why it is asked")
        if len(draft.text) > MAX_QUESTION_CHARS:
            raise GapFillError(f"a question is at most {MAX_QUESTION_CHARS} characters")
        choices = [c for c in draft.choices if c.strip()]
        if draft.answer_type.has_choices:
            if not MIN_CHOICES <= len(choices) <= MAX_CHOICES or len(set(choices)) != len(choices):
                raise GapFillError(
                    f"a choice question offers {MIN_CHOICES} to {MAX_CHOICES} distinct choices"
                )
        elif choices:
            raise GapFillError("a free-text question offers no choices")
        per_gap[draft.gap_key] = per_gap.get(draft.gap_key, 0) + 1
        if per_gap[draft.gap_key] > MAX_QUESTIONS_PER_GAP:
            raise GapFillError(f"at most {MAX_QUESTIONS_PER_GAP} questions per gap")


def answer_fact(
    *, text: str, answer_type: AnswerType, choices: Sequence[str], answer: Answer
) -> str | None:
    """The answer as one fact to store as evidence, or ``None`` when the user
    left the question blank, which leaves its gap open.

    A choice must be one of the question's; free text is trimmed and bounded.
    """
    choice = (answer.choice or "").strip() or None
    said = (answer.text or "").strip() or None
    if choice is not None:
        if not answer_type.has_choices:
            raise GapFillError("that question takes no choice")
        if choice not in choices:
            raise GapFillError("that choice is not one the question offered")
    if said is not None:
        if answer_type is AnswerType.CHOICE:
            raise GapFillError("that question takes a choice only")
        if len(said) > MAX_ANSWER_CHARS:
            raise GapFillError(f"an answer is at most {MAX_ANSWER_CHARS} characters")
    if choice is None and said is None:
        return None
    reply = " — ".join(part for part in (choice, said) if part)
    return f"{text.strip()} {reply}"


class QuestionSetStatus(StrEnum):
    """A set is written in the background, so it is recorded before it starts
    and the page polls it (ADR 0006). A newer set for the same Target
    supersedes it."""

    WRITING = "writing"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class QuestionSet:
    """The questions written for one Target's gaps (domain decision 27)."""

    id: uuid.UUID
    owner_id: uuid.UUID
    # The Target (ADR 0022): a role, and optionally one opening in it.
    role_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    label: str
    status: QuestionSetStatus
    gaps: tuple[AskedGap, ...]
    created_at: datetime
    model_id: str | None = None
    template_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    written_at: datetime | None = None
    submitted_at: datetime | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        role_id: uuid.UUID,
        job_posting_id: uuid.UUID | None,
        label: str,
        gaps: tuple[AskedGap, ...],
        at: datetime,
    ) -> QuestionSet:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            label=label[:400],
            status=QuestionSetStatus.WRITING,
            gaps=gaps,
            created_at=at,
        )

    @property
    def is_open(self) -> bool:
        """Still the Target's current set: writing, or written and not yet
        submitted."""
        return self.status is QuestionSetStatus.WRITING or (
            self.status is QuestionSetStatus.READY and self.submitted_at is None
        )

    def written(self, *, model_id: str, template_version: str, at: datetime) -> None:
        self.status = QuestionSetStatus.READY
        self.model_id = model_id
        self.template_version = template_version
        self.written_at = at

    def failed(self, *, code: str, message: str) -> None:
        self.status = QuestionSetStatus.FAILED
        self.error_code = code
        self.error_message = message

    def supersede(self) -> None:
        self.status = QuestionSetStatus.SUPERSEDED

    def submitted(self, at: datetime) -> None:
        self.submitted_at = at


@dataclass(slots=True)
class GapQuestion:
    """One question about one gap. Its answer is not stored here while the
    user types: it arrives with the one submit, and becomes evidence."""

    id: uuid.UUID
    owner_id: uuid.UUID
    set_id: uuid.UUID
    position: int
    gap_key: str
    gap_label: str
    gap_status: GapStatus
    lift: int
    text: str
    asked_because: str
    answer_type: AnswerType
    choices: tuple[str, ...]
    evidence_id: uuid.UUID | None = None
    answered_at: datetime | None = None

    def answered(self, evidence_id: uuid.UUID, at: datetime) -> None:
        self.evidence_id = evidence_id
        self.answered_at = at
