"""Evidence: one cited fact about the user's work.

Evidence is what makes a skill score explainable and what lets a resume bullet
be traced to real work. It is the main guard against the model inventing
claims, so the rules here are enforced on every AI output that cites an id
(domain section 2.3).

``CareerProfile`` holds facts only. It never holds a score.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class EvidenceSource(StrEnum):
    GITHUB = "github"
    JIRA = "jira"
    RESUME = "resume"
    # A user's answer to a follow-up question, stored as self-reported evidence.
    SELF_REPORTED = "self_reported"


class EvidenceGranularity(StrEnum):
    """Whether a fact is one piece of work or a tally over many.

    An ``item`` is one commit, one issue or one résumé line; its
    ``observed_on`` is when that work happened. A ``summary`` counts many items
    ("12 commits authored in x") and its date is only the latest of them,
    so anything that counts work over time must count items alone.
    """

    ITEM = "item"
    SUMMARY = "summary"


@dataclass(slots=True)
class Evidence:
    """One cited fact. ``reference`` is where a human can go and check it.

    ``external_ref`` identifies the fact at its source, so re-syncing a source
    restates a fact rather than duplicating it.

    ``subject`` is the repository or project the work belongs to, when the
    source has one. ``tally`` is how many items a summary counts, so it can be
    compared without reading a number back out of the sentence.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    source: EvidenceSource
    external_ref: str
    reference: str
    fact: str
    observed_on: date | None
    confidence: float
    granularity: EvidenceGranularity = EvidenceGranularity.ITEM
    tally: int | None = None
    subject: str | None = None
    source_connection_id: uuid.UUID | None = None
    resume_file_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_confidence(self.confidence)
        _check_tally(self.granularity, self.tally)

    @classmethod
    def cited(
        cls,
        *,
        owner_id: uuid.UUID,
        source: EvidenceSource,
        external_ref: str,
        reference: str,
        fact: str,
        observed_on: date | None,
        confidence: float,
        granularity: EvidenceGranularity = EvidenceGranularity.ITEM,
        tally: int | None = None,
        subject: str | None = None,
        source_connection_id: uuid.UUID | None = None,
        resume_file_id: uuid.UUID | None = None,
    ) -> Evidence:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            source=source,
            external_ref=external_ref,
            reference=reference,
            fact=fact,
            observed_on=observed_on,
            confidence=confidence,
            granularity=granularity,
            tally=tally,
            subject=subject,
            source_connection_id=source_connection_id,
            resume_file_id=resume_file_id,
        )

    def restate(
        self,
        *,
        reference: str,
        fact: str,
        observed_on: date | None,
        confidence: float,
        granularity: EvidenceGranularity,
        tally: int | None,
        subject: str | None,
    ) -> None:
        """A re-sync brings the fact up to date; where it came from stays."""
        _check_confidence(confidence)
        _check_tally(granularity, tally)
        self.reference = reference
        self.fact = fact
        self.observed_on = observed_on
        self.confidence = confidence
        self.granularity = granularity
        self.tally = tally
        self.subject = subject

    def found_in_resume(self, resume_file_id: uuid.UUID) -> None:
        """A newer upload restated this line, so the line is that upload's now.

        Removing a résumé removes the lines it owns. Moving a line to the
        newest file that states it means removing an older copy keeps it, and
        removing the newest takes it away.
        """
        self.resume_file_id = resume_file_id


def _check_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("evidence confidence must be between 0 and 1")


def _check_tally(granularity: EvidenceGranularity, tally: int | None) -> None:
    if tally is None:
        return
    if granularity is not EvidenceGranularity.SUMMARY:
        raise ValueError("only a summary tallies items")
    if tally < 0:
        raise ValueError("a tally cannot be negative")


class CitationError(Exception):
    """The model cited evidence that is not in this user's profile."""

    def __init__(self, invented: frozenset[str]) -> None:
        super().__init__(f"output cites evidence that does not exist: {sorted(invented)}")
        self.invented = invented


def assert_citations_exist(cited: set[str], owned: set[str]) -> None:
    """Reject AI output that cites evidence the user does not have.

    This is checked against *this user's* evidence, so a prompt-injected id
    from a crawled page or an uploaded file cannot smuggle a claim in, and the
    model cannot decorate a resume with work that never happened.
    """
    invented = cited - owned
    if invented:
        raise CitationError(frozenset(invented))


class CitationHandles:
    """Short names the model cites evidence by, in place of its ids.

    Copying a 36-character id back exactly is where a model slips: one wrong
    character and a real citation reads as an invented one, failing the whole
    reply. ``E12`` is hard to garble. Resolving stays strict — a handle that was
    never handed out is an invented citation — and the ids it resolves to still
    go through ``assert_citations_exist``.
    """

    def __init__(self, evidence_ids: Iterable[object]) -> None:
        self._ids = {f"E{n}": str(i) for n, i in enumerate(evidence_ids, start=1)}
        self._handles = {i: handle for handle, i in self._ids.items()}

    def handle(self, evidence_id: object) -> str:
        """The handle an id is shown under; an id never given one shows as itself."""
        return self._handles.get(str(evidence_id), str(evidence_id))

    def resolve(self, cited: Iterable[str]) -> tuple[str, ...]:
        """The ids behind the cited handles, in order."""
        cited = tuple(cited)
        invented = {handle for handle in cited if handle not in self._ids}
        if invented:
            raise CitationError(frozenset(invented))
        return tuple(self._ids[handle] for handle in cited)
