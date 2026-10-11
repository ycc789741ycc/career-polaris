"""Fill the gap's rules: what a written question must be, and what counts as an
answer. Pure — no storage, no model."""

from __future__ import annotations

import uuid

import pytest

from advisor.gapfill.domain import (
    MAX_QUESTIONS_PER_GAP,
    Answer,
    AnswerType,
    AskedGap,
    DraftQuestion,
    GapFillError,
    GapStatus,
    ReadingDraft,
    answer_fact,
    assert_questions_valid,
    get_readings_settled,
)

GAPS = (
    AskedGap("dim:incidents", "Own incidents end to end", GapStatus.PARTIAL, 9),
    AskedGap("req:multi-region", "Multi-region capacity planning", GapStatus.NO_EVIDENCE, 4),
)


def question(**overrides: object) -> DraftQuestion:
    values: dict[str, object] = {
        "gap_key": "dim:incidents",
        "text": "Have you been on an on-call rotation?",
        "asked_because": "Incident response rests on one review.",
        "answer_type": AnswerType.CHOICE,
        "choices": ("Yes, as primary", "As secondary", "Never"),
    }
    values.update(overrides)
    return DraftQuestion(**values)  # type: ignore[arg-type]


def test_questions_about_the_asked_gaps_are_accepted() -> None:
    assert_questions_valid(
        [
            question(),
            question(
                gap_key="req:multi-region",
                answer_type=AnswerType.FREE_TEXT,
                choices=(),
            ),
        ],
        GAPS,
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"gap_key": "dim:unknown"},
        {"text": "  "},
        {"asked_because": ""},
        {"choices": ("Only one",)},
        {"choices": ("Same", "Same")},
        {"answer_type": AnswerType.FREE_TEXT},
    ],
)
def test_a_question_the_rules_do_not_allow_is_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(GapFillError):
        assert_questions_valid([question(**bad)], GAPS)


def test_no_questions_at_all_is_rejected() -> None:
    with pytest.raises(GapFillError):
        assert_questions_valid([], GAPS)


def test_a_gap_gets_a_few_questions_at_most() -> None:
    with pytest.raises(GapFillError, match="per gap"):
        assert_questions_valid([question()] * (MAX_QUESTIONS_PER_GAP + 1), GAPS)


def _answer(choice: str | None = None, text: str | None = None) -> Answer:
    return Answer(question_id=uuid.uuid4(), choice=choice, text=text)


def test_a_choice_becomes_a_fact_naming_the_question() -> None:
    fact = answer_fact(
        text="On call?",
        answer_type=AnswerType.CHOICE,
        choices=("Yes", "No"),
        answer=_answer("Yes"),
    )
    assert fact == "On call? Yes"


def test_a_choice_with_words_keeps_both() -> None:
    fact = answer_fact(
        text="Led an incident?",
        answer_type=AnswerType.BOTH,
        choices=("Yes", "Not yet"),
        answer=_answer("Yes", "  The Feb payment outage. "),
    )
    assert fact == "Led an incident? Yes — The Feb payment outage."


def test_a_blank_answer_leaves_the_gap_open() -> None:
    assert (
        answer_fact(
            text="Q?", answer_type=AnswerType.BOTH, choices=("a", "b"), answer=_answer(None, " ")
        )
        is None
    )


@pytest.mark.parametrize(
    ("answer_type", "answer"),
    [
        (AnswerType.CHOICE, _answer("Maybe")),
        (AnswerType.CHOICE, _answer(None, "free words")),
        (AnswerType.FREE_TEXT, _answer("Yes")),
        (AnswerType.FREE_TEXT, _answer(None, "x" * 2001)),
    ],
)
def test_an_answer_the_question_does_not_take_is_refused(
    answer_type: AnswerType, answer: Answer
) -> None:
    with pytest.raises(GapFillError):
        answer_fact(text="Q?", answer_type=answer_type, choices=("Yes", "No"), answer=answer)


# --- reading the answers into the fit (ADR 0077) -----------------------------


def test_a_reading_stands_only_on_its_own_gaps_answers_with_what_its_kind_needs() -> None:
    answers = {"dim:incidents": {"a1"}, "req:capacity": {"a2"}}
    drafts = [
        ReadingDraft("dim:incidents", 75, None, "Led it.", ("a1",)),
        # Cites another gap's answer.
        ReadingDraft("req:capacity", None, "covered", "Borrowed.", ("a1",)),
        # A gap nobody answered.
        ReadingDraft("dim:other", 50, None, "Unasked.", ("a1",)),
        # A dimension with no score.
        ReadingDraft("dim:incidents", None, "covered", "Wrong kind.", ("a1",)),
        ReadingDraft("req:capacity", None, "partly", "Planned one region.", ("a2",)),
        # The same gap again: the first written stands.
        ReadingDraft("req:capacity", None, "covered", "Again.", ("a2",)),
    ]

    settled = get_readings_settled(drafts, answers)

    assert [(r.gap_key, r.score, r.coverage) for r in settled] == [
        ("dim:incidents", 75, None),
        ("req:capacity", None, "partly"),
    ]


def test_a_reading_citing_nothing_does_not_stand() -> None:
    drafts = [ReadingDraft("dim:incidents", 75, None, "Led it.", ())]

    assert get_readings_settled(drafts, {"dim:incidents": {"a1"}}) == ()
