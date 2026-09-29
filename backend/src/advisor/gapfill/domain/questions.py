"""The rules of Fill the gap (domain decision 27): which gaps are asked about,
what a written question must look like, and what counts as an answer.

Pure: no I/O, no framework, no kernel.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

# The costliest gaps of a Target are asked about, as the gap plan shows them.
ASKED_GAPS = 4
MAX_QUESTIONS_PER_GAP = 3
MIN_CHOICES = 2
MAX_CHOICES = 5
MAX_QUESTION_CHARS = 400
MAX_ANSWER_CHARS = 2000


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
