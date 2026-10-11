"""Reading submitted answers into a Target's fit (ADR 0077): which of the
model's readings stand.

A reading is about one gap the user answered, says what its kind needs — a
dimension gap a score, an uncovered requirement a coverage — and cites the
answers given about that gap and nothing else. One that does not is dropped,
not the whole reply: the rest still move the fit (as ADR 0074 drops a gap
plan's stray citations).

Pure: no I/O, no framework, no kernel.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

COVERAGES = ("covered", "partly", "not")


@dataclass(frozen=True, slots=True)
class ReadingDraft:
    """A reading as the model wrote it, its citations already resolved to
    evidence ids."""

    gap_key: str
    score: int | None
    coverage: str | None
    reasoning: str
    evidence_ids: tuple[str, ...]


def get_readings_settled(
    drafts: Sequence[ReadingDraft], answers_by_gap: Mapping[str, set[str]]
) -> tuple[ReadingDraft, ...]:
    """The readings that stand, one per gap (the first written), in the
    order they came. ``answers_by_gap`` is each answered gap's answer
    evidence ids, by gap key (``dim:`` or ``req:``)."""
    kept: dict[str, ReadingDraft] = {}
    for draft in drafts:
        answers = answers_by_gap.get(draft.gap_key)
        if answers is None or draft.gap_key in kept:
            continue
        if not draft.evidence_ids or not set(draft.evidence_ids) <= answers:
            continue
        if draft.gap_key.startswith("dim:"):
            if draft.score is None or not 0 <= draft.score <= 100:
                continue
            kept[draft.gap_key] = ReadingDraft(
                draft.gap_key, draft.score, None, draft.reasoning, draft.evidence_ids
            )
        elif draft.coverage in COVERAGES:
            kept[draft.gap_key] = ReadingDraft(
                draft.gap_key, None, draft.coverage, draft.reasoning, draft.evidence_ids
            )
    return tuple(kept.values())
