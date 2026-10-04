"""The career profile.

Holds the CareerProfile: a career timeline plus every piece of Evidence for
one user. Facts only — a score never lives here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from fnmatch import fnmatchcase

from advisor.profile.domain import (
    CareerPositionFilter,
    CitationError,
    CitationHandles,
    Evidence,
    EvidenceFilter,
    EvidenceGranularity,
    EvidenceSource,
    OwnerProfile,
    ProfileUnitOfWork,
    ProfileUpdated,
    ProfileVersion,
    ProfileVersionFilter,
    ResumeFile,
    ResumeFileFilter,
    ResumeStatus,
    SourceConnection,
    SourceConnectionFilter,
    SourceSynced,
    assert_citations_exist,
    get_date_label,
    get_shown_date,
    total_experience_months,
)
from advisor.profile.domain import (
    Position as PositionValue,
)
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from advisor.profile.infra.resume_parser import parse
from kernel.clock import utcnow
from kernel.crypto import decrypt, encrypt
from kernel.documents import ACCEPTED_TYPES
from kernel.errors import NotFoundError, UpstreamFailedError, ValidationError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from kernel.paging import Page
from kernel.storage import ObjectStore, object_key

__all__ = [
    "ACCEPTED_TYPES",
    "AnswerRecord",
    "CitationError",
    "CitationHandles",
    "ConnectionView",
    "EvidenceSource",
    "EvidenceView",
    "PendingSourceView",
    "ProfileService",
    "ProfileSnapshot",
    "ResumeFileView",
    "SourceProcessingView",
    "assert_citations_exist",
    "get_evidence_line",
]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConnectionView:
    kind: str
    account: str | None
    status: str
    last_synced_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class EvidenceView:
    id: uuid.UUID
    source: EvidenceSource
    reference: str
    fact: str
    observed_on: date | None
    granularity: EvidenceGranularity
    tally: int | None
    subject: str | None
    # A résumé line's stated date: the day the file it was last found in was
    # uploaded. None for every other source (ADR 0037).
    stated_on: date | None = None

    @property
    def shown_on(self) -> date | None:
        """The date the fact is shown and ordered by."""
        return get_shown_date(
            source=self.source, observed_on=self.observed_on, stated_on=self.stated_on
        )


def get_evidence_line(evidence: EvidenceView, handle: str | None = None) -> str:
    """One fact as every prompt shows it: its handle when it can be cited, the
    source and what its date means, then where it is from and what it says
    (ADR 0037). Only the platform writes the date part. Pure."""
    label = get_date_label(
        source=evidence.source,
        granularity=evidence.granularity,
        observed_on=evidence.observed_on,
        stated_on=evidence.stated_on,
    )
    cited = f"[{handle}] " if handle is not None else ""
    return f"{cited}({evidence.source}, {label}) {evidence.reference}: {evidence.fact}"


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """An answer to store as evidence: the question it answers and the fact,
    written as the question with the user's reply."""

    question_id: str
    fact: str


@dataclass(frozen=True, slots=True)
class ResumeFileView:
    id: uuid.UUID
    filename: str
    status: str
    parse_error: str | None
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class PendingSourceView:
    """One source still being turned into evidence: a sync or a parse."""

    label: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class SourceProcessingView:
    """What stage 01 is still working on. An analysis waits until both are
    empty, or it would miss the evidence they are about to write (ADR 0018)."""

    syncing: tuple[PendingSourceView, ...]
    parsing: tuple[PendingSourceView, ...]


@dataclass(frozen=True, slots=True)
class SourceAccountView:
    """Whose work a connected source holds: the GitHub login, the Jira site.
    What tells a person's own repositories from other people's (ADR 0043)."""

    source: str
    account: str


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """What the assessment reads. Facts and a version, never a score."""

    version: int
    evidence: tuple[EvidenceView, ...]
    positions: tuple[PositionValue, ...]
    total_experience_months: int
    accounts: tuple[SourceAccountView, ...] = ()


class ProfileService:
    def __init__(
        self,
        uow: ProfileUnitOfWork,
        *,
        object_store: ObjectStore,
        connectors: dict[str, Connector],
        resume_max_bytes: int,
        resume_max_pages: int,
        http_timeout_seconds: float,
        user_agent: str,
    ) -> None:
        self._uow = uow
        self._store = object_store
        self._connectors = connectors
        self._resume_max_bytes = resume_max_bytes
        self._resume_max_pages = resume_max_pages
        self._http_timeout = http_timeout_seconds
        self._user_agent = user_agent

    # -- connections --------------------------------------------------------

    def _connector(self, kind: str) -> Connector:
        connector = self._connectors.get(kind)
        if connector is None:
            raise ValidationError(f"unknown connector {kind!r}", kind=kind)
        return connector

    async def connections(self, owner_id: uuid.UUID) -> list[ConnectionView]:
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.connections.get_list(SourceConnectionFilter())
        return [_connection_view(c) for c in found]

    async def store_connection(
        self,
        owner_id: uuid.UUID,
        *,
        kind: str,
        access_token: str,
        refresh_token: str | None,
        scopes: tuple[str, ...],
        expires_at: datetime | None,
    ) -> ConnectionView:
        """Store fresh tokens, and record which account they belong to.

        The account is looked up before anything is written, so a token the
        provider will not identify never becomes a connection.
        """
        connector = self._connector(kind)
        async with GuardedClient(
            timeout_seconds=self._http_timeout, user_agent=self._user_agent
        ) as client:
            account = await connector.account_name(client, access_token)

        async with self._uow.for_owner(owner_id) as mine:
            existing = await _connection(mine, kind)
            connection = existing or SourceConnection.new(owner_id=owner_id, kind=kind)
            connection.authorise(
                encrypted_access_token=encrypt(access_token, context=str(owner_id)),
                encrypted_refresh_token=(
                    encrypt(refresh_token, context=str(owner_id)) if refresh_token else None
                ),
                scopes=scopes,
                expires_at=expires_at,
                account=account,
            )
            if existing is None:
                stored = await mine.connections.create(connection)
            else:
                stored = await mine.connections.update(connection)
            return _connection_view(stored)

    async def disconnect(self, owner_id: uuid.UUID, kind: str) -> None:
        """Drop the tokens and every fact gathered from that source.

        Removing the evidence is what makes switching accounts safe: facts from
        the old account never mix with the new one's. Matching on ``source``
        rather than the connection id also sweeps facts orphaned by a
        disconnect made before this rule existed.
        """
        self._connector(kind)
        async with self._uow.for_owner(owner_id) as mine:
            connection = await _connection(mine, kind)
            if connection is None:
                return
            await mine.connections.delete(connection.id)

            source = EvidenceSource(kind)
            removed = 0
            while stale := await mine.evidence.get_list(EvidenceFilter(source=source)):
                for evidence in stale:
                    await mine.evidence.delete(evidence.id)
                removed += len(stale)

            version = await _bump_version(mine, owner_id, utcnow())
            mine.record(
                ProfileUpdated(
                    owner_id=owner_id, source=source, version=version.version, count=removed
                )
            )
            log.info("connection.disconnected", kind=kind, evidence_removed=removed)

    async def request_sync(self, owner_id: uuid.UUID, kind: str) -> ConnectionView:
        """Mark a sync as started before it is queued, so the page shows it
        running from the moment it is asked for (ADR 0006, ADR 0018)."""
        async with self._uow.for_owner(owner_id) as mine:
            connection = await _connection(mine, kind)
            if connection is None:
                raise NotFoundError(f"{kind} is not connected", kind=kind)
            connection.sync_requested(utcnow())
            return _connection_view(await mine.connections.update(connection))

    async def sync_connection(self, owner_id: uuid.UUID, kind: str) -> int:
        """Fetch a source and turn it into Evidence. Worker `sync` queue only.

        This is the one place besides the AI gateway where a stored secret is
        opened, and the token never leaves this call. However it ends, the
        connection stops showing as syncing.
        """
        try:
            return await self._sync_connection(owner_id, kind)
        except UpstreamFailedError as exc:
            await self._sync_failed(owner_id, kind, exc.message)
            raise
        except Exception:
            await self._sync_failed(
                owner_id, kind, "The sync stopped unexpectedly. Try again in a moment."
            )
            raise

    async def _sync_failed(self, owner_id: uuid.UUID, kind: str, error: str) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            failed = await _connection(mine, kind)
            if failed is not None:
                failed.sync_failed(error)
                await mine.connections.update(failed)

    async def _sync_connection(self, owner_id: uuid.UUID, kind: str) -> int:
        connector = self._connector(kind)

        async with self._uow.for_owner(owner_id) as mine:
            connection = await _connection(mine, kind)
            if connection is None:
                raise NotFoundError(f"{kind} is not connected", kind=kind)
            token = decrypt(connection.encrypted_access_token, context=str(owner_id))
            connection_id = connection.id

        async with GuardedClient(
            timeout_seconds=self._http_timeout, user_agent=self._user_agent
        ) as client:
            account = await connector.account_name(client, token)
            drafts = await connector.fetch(client, token)

        written = await self._write_evidence(
            owner_id,
            EvidenceSource(kind),
            drafts,
            source_connection_id=connection_id,
            retired_refs=connector.retired_refs,
            replaced_refs=connector.replaced_refs,
        )

        async with self._uow.for_owner(owner_id) as mine:
            synced = await mine.connections.get(connection_id)
            if synced is not None:
                synced.synced(utcnow(), account=account)
                await mine.connections.update(synced)
            mine.record(SourceSynced(owner_id=owner_id, kind=kind, evidence=written))
        return written

    # -- resume -------------------------------------------------------------

    async def upload_resume(
        self, owner_id: uuid.UUID, *, filename: str, content_type: str, content: bytes
    ) -> ResumeFileView:
        """Store the file and return. Parsing is a worker job, never inline."""
        if len(content) > self._resume_max_bytes:
            raise ValidationError(
                "this file is larger than we accept", limit_bytes=self._resume_max_bytes
            )
        if content_type not in ACCEPTED_TYPES:
            raise ValidationError(
                f"{content_type} is not a resume format we can read",
                content_type=content_type,
            )

        resume_id = uuid.uuid4()
        key = object_key(owner_id, "resumes", f"{resume_id}")
        self._store.put(key, content, content_type)

        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.resumes.create(
                ResumeFile(
                    id=resume_id,
                    owner_id=owner_id,
                    filename=filename,
                    storage_key=key,
                    content_type=content_type,
                    byte_size=len(content),
                    status=ResumeStatus.UPLOADED,
                )
            )
        return _resume_view(stored)

    async def parse_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        """Worker `sync` queue. Parsing never happens in a request handler.

        However it ends, the résumé stops showing as parsing: an unexpected
        failure is recorded too, and re-raised for the log.
        """
        try:
            return await self._parse_resume(owner_id, resume_id)
        except ValidationError as exc:
            await self._parse_failed(owner_id, resume_id, exc.message)
            raise
        except Exception:
            await self._parse_failed(
                owner_id,
                resume_id,
                "Reading this file stopped unexpectedly. Try uploading it again.",
            )
            raise

    async def _parse_failed(self, owner_id: uuid.UUID, resume_id: uuid.UUID, error: str) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            failed = await mine.resumes.get(resume_id)
            if failed is not None and failed.status is ResumeStatus.UPLOADED:
                failed.parse_failed(error)
                await mine.resumes.update(failed)

    async def _parse_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
            if resume is None:
                raise NotFoundError("resume not found", resume_id=str(resume_id))

        content = self._store.get(resume.storage_key)
        parsed = parse(
            content,
            content_type=resume.content_type,
            filename=resume.filename,
            max_pages=self._resume_max_pages,
        )

        written = await self._write_evidence(
            owner_id, EvidenceSource.RESUME, parsed.drafts, resume_file_id=resume_id
        )
        async with self._uow.for_owner(owner_id) as mine:
            done = await mine.resumes.get(resume_id)
            if done is not None:
                done.parsed(utcnow())
                await mine.resumes.update(done)
        return written

    async def processing(self, owner_id: uuid.UUID) -> SourceProcessingView:
        """The syncs and parses still running, oldest first."""
        async with self._uow.for_owner(owner_id) as mine:
            connections = await mine.connections.get_list(SourceConnectionFilter())
            pending = await mine.resumes.get_list(ResumeFileFilter(status=ResumeStatus.UPLOADED))
        syncing = [
            PendingSourceView(label=c.kind, started_at=c.sync_started_at)
            for c in connections
            if c.sync_started_at is not None
        ]
        parsing = [
            PendingSourceView(label=r.filename, started_at=r.created_at)
            for r in pending
            if r.created_at is not None
        ]
        return SourceProcessingView(
            syncing=tuple(sorted(syncing, key=lambda p: p.started_at)),
            parsing=tuple(sorted(parsing, key=lambda p: p.started_at)),
        )

    async def base_resume_text(self, owner_id: uuid.UUID, *, max_chars: int = 12_000) -> str | None:
        """The latest parsed résumé's text: what a new résumé revises, not replaces.

        Worker only — parsing never happens in a request handler. None when the
        user has not uploaded one that parsed.
        """
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get_latest_parsed()
        if resume is None:
            return None

        parsed = parse(
            self._store.get(resume.storage_key),
            content_type=resume.content_type,
            filename=resume.filename,
            max_pages=self._resume_max_pages,
        )
        return parsed.text[:max_chars]

    async def resumes(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[ResumeFileView]:
        """Newest first, paged by the store."""
        everything = ResumeFileFilter()
        async with self._uow.for_owner(owner_id) as mine:
            uploaded = await mine.resumes.get_list(everything, page=page, page_size=page_size)
            total = await mine.resumes.get_count(everything)
        return Page(tuple(_resume_view(r) for r in uploaded), page, page_size, total)

    async def evidence(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[EvidenceView]:
        """Every fact on the profile, newest first, paged by the store.

        The one list that grows with every sync. ``snapshot`` still reads it
        whole, for the assessment, which reasons over all of it.
        """
        everything = EvidenceFilter()
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.evidence.get_list(everything, page=page, page_size=page_size)
            total = await mine.evidence.get_count(everything)
            uploaded = await _upload_dates(mine)
        return Page(tuple(_evidence_view(e, uploaded) for e in found), page, page_size, total)

    async def delete_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        """Remove an uploaded résumé and every line of evidence it owns.

        The stored file goes first: deleting an object is idempotent, so if the
        database step then fails, trying again finishes the job, rather than
        leaving a row that points at nothing or a file nothing points at.
        """
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
        if resume is None:
            raise NotFoundError("resume not found", resume_id=str(resume_id))

        self._store.delete(resume.storage_key)

        async with self._uow.for_owner(owner_id) as mine:
            owned = EvidenceFilter(resume_file_id=resume_id)
            removed = 0
            while stale := await mine.evidence.get_list(owned):
                for evidence in stale:
                    await mine.evidence.delete(evidence.id)
                removed += len(stale)
            await mine.resumes.delete(resume_id)

            version = await _bump_version(mine, owner_id, utcnow())
            mine.record(
                ProfileUpdated(
                    owner_id=owner_id,
                    source=EvidenceSource.RESUME,
                    version=version.version,
                    count=removed,
                )
            )
        log.info("resume.deleted", evidence_removed=removed)

    async def resume_download_url(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> str:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
        if resume is None:
            raise NotFoundError("resume not found", resume_id=str(resume_id))
        return self._store.signed_url(resume.storage_key)

    # -- answers ------------------------------------------------------------

    async def record_answer(
        self, owner_id: uuid.UUID, *, question_id: str, question: str, answer: str
    ) -> EvidenceView:
        """One answer, stored as ``user_answer`` evidence."""
        if not answer.strip():
            raise ValidationError("an answer is required")
        [stored] = await self.record_answers(
            owner_id,
            [AnswerRecord(question_id=question_id, fact=f"{question} — {answer.strip()}")],
        )
        return stored

    async def record_answers(
        self, owner_id: uuid.UUID, answers: Sequence[AnswerRecord]
    ) -> list[EvidenceView]:
        """Answers from one submit of Fill the gap, stored as ``user_answer``
        evidence in one transaction, with one ``ProfileUpdated`` (domain
        decision 27). Ingestion stays deterministic: the fact is the question
        and the answer as the user gave it, and nothing reads it with a model."""
        if not answers:
            raise ValidationError("there are no answers to record")
        if any(not a.fact.strip() for a in answers):
            raise ValidationError("an answer is required")
        drafts = [
            EvidenceDraft(
                external_ref=_answer_ref(a.question_id),
                reference="Your answer",
                fact=a.fact.strip(),
                observed_on=utcnow().date(),
            )
            for a in answers
        ]
        await self._write_evidence(owner_id, EvidenceSource.USER_ANSWER, drafts)
        refs = tuple(d.external_ref for d in drafts)
        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.evidence.get_list(
                EvidenceFilter(source=EvidenceSource.USER_ANSWER, external_refs=refs)
            )
        by_ref = {e.external_ref: e for e in stored}
        if set(by_ref) != set(refs):
            raise NotFoundError("an answer was not stored", count=len(refs) - len(by_ref))
        return [_evidence_view(by_ref[ref]) for ref in refs]

    # -- reading the profile ------------------------------------------------

    async def snapshot(self, owner_id: uuid.UUID) -> ProfileSnapshot:
        """Every fact, newest first, with the timeline and the version.

        Ordered by the date each fact is shown with, undated last (ADR 0037),
        so a prompt that shows only the first so many drops the oldest. One
        user's profile: bounded by what they connected and uploaded, and read
        whole because the assessment reasons over all of it.
        """
        async with self._uow.for_owner(owner_id) as mine:
            evidence = await mine.evidence.get_list(EvidenceFilter())
            timeline = await mine.positions.get_list(CareerPositionFilter())
            versions = await mine.versions.get_list(ProfileVersionFilter(), page_size=1)
            uploaded = await _upload_dates(mine)
            connections = await mine.connections.get_list(SourceConnectionFilter())
        positions = tuple(p.value for p in timeline)
        return ProfileSnapshot(
            version=versions[0].version if versions else 0,
            evidence=get_newest_first(_evidence_view(e, uploaded) for e in evidence),
            positions=positions,
            total_experience_months=total_experience_months(list(positions), as_of=utcnow().date()),
            accounts=tuple(
                SourceAccountView(source=c.kind, account=c.external_account)
                for c in sorted(connections, key=lambda c: c.kind)
                if c.external_account
            ),
        )

    async def version(self, owner_id: uuid.UUID) -> int:
        """The profile's current version: bumped by every change to its evidence."""
        async with self._uow.for_owner(owner_id) as mine:
            versions = await mine.versions.get_list(ProfileVersionFilter(), page_size=1)
        return versions[0].version if versions else 0

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        """Used to reject AI output citing evidence this user does not have."""
        async with self._uow.for_owner(owner_id) as mine:
            evidence = await mine.evidence.get_list(EvidenceFilter())
        return {str(e.id) for e in evidence}

    # -- internals ----------------------------------------------------------

    async def _write_evidence(
        self,
        owner_id: uuid.UUID,
        source: EvidenceSource,
        drafts: list[EvidenceDraft],
        *,
        source_connection_id: uuid.UUID | None = None,
        resume_file_id: uuid.UUID | None = None,
        retired_refs: tuple[str, ...] = (),
        replaced_refs: tuple[str, ...] = (),
    ) -> int:
        """Upsert by ``external_ref`` so a re-sync updates rather than duplicates.

        Facts matching ``retired_refs`` — shapes the source's connector no
        longer writes — are deleted first, so old and new shapes never both count.
        Facts matching ``replaced_refs`` that are not among ``drafts`` are
        deleted too: the source no longer backs them.
        Bumps the profile version and records ``ProfileUpdated`` in the same
        transaction. Per domain section 2.9 this does not start an analysis —
        the user asks for that explicitly.
        """
        if not drafts and not retired_refs and not replaced_refs:
            return 0

        async with self._uow.for_owner(owner_id) as mine:
            written = {d.external_ref for d in drafts}
            retired = await _retire(mine, source, retired_refs) + await _retire(
                mine, source, replaced_refs, keep=written
            )
            if not drafts and not retired:
                return 0

            existing = await mine.evidence.get_list(
                EvidenceFilter(source=source, external_refs=tuple(d.external_ref for d in drafts))
            )
            by_ref = {e.external_ref: e for e in existing}

            for draft in drafts:
                known = by_ref.get(draft.external_ref)
                if known is None:
                    await mine.evidence.create(
                        Evidence.cited(
                            owner_id=owner_id,
                            source=source,
                            external_ref=draft.external_ref,
                            reference=draft.reference,
                            fact=draft.fact,
                            observed_on=draft.observed_on,
                            granularity=draft.granularity,
                            tally=draft.tally,
                            subject=draft.subject,
                            source_connection_id=source_connection_id,
                            resume_file_id=resume_file_id,
                        )
                    )
                else:
                    known.restate(
                        reference=draft.reference,
                        fact=draft.fact,
                        observed_on=draft.observed_on,
                        granularity=draft.granularity,
                        tally=draft.tally,
                        subject=draft.subject,
                    )
                    if resume_file_id is not None:
                        known.found_in_resume(resume_file_id)
                    await mine.evidence.update(known)

            version = await _bump_version(mine, owner_id, utcnow())
            mine.record(
                ProfileUpdated(
                    owner_id=owner_id,
                    source=source,
                    version=version.version,
                    count=len(drafts) + retired,
                )
            )
            return len(drafts)


async def _retire(
    mine: OwnerProfile,
    source: EvidenceSource,
    patterns: tuple[str, ...],
    *,
    keep: frozenset[str] | set[str] = frozenset(),
) -> int:
    """Delete a source's facts whose ``external_ref`` matches any of the glob ``patterns``.

    A fact whose ``external_ref`` is in ``keep`` stays.
    """
    if not patterns:
        return 0
    stale = [
        e
        for e in await mine.evidence.get_list(EvidenceFilter(source=source))
        if e.external_ref not in keep
        and any(fnmatchcase(e.external_ref, pattern) for pattern in patterns)
    ]
    for evidence in stale:
        await mine.evidence.delete(evidence.id)
    if stale:
        log.info("evidence.retired", source=str(source), evidence_removed=len(stale))
    return len(stale)


async def _bump_version(mine: OwnerProfile, owner_id: uuid.UUID, now: datetime) -> ProfileVersion:
    versions = await mine.versions.get_list(ProfileVersionFilter(), page_size=1)
    if versions:
        version = versions[0]
        version.bump(now)
        return await mine.versions.update(version)
    return await mine.versions.create(ProfileVersion.first(owner_id=owner_id, at=now))


async def _connection(mine: OwnerProfile, kind: str) -> SourceConnection | None:
    found = await mine.connections.get_list(SourceConnectionFilter(kind=kind), page_size=1)
    return found[0] if found else None


def _connection_view(connection: SourceConnection) -> ConnectionView:
    return ConnectionView(
        kind=connection.kind,
        account=connection.external_account,
        status=str(connection.status),
        last_synced_at=connection.last_synced_at,
        last_error=connection.last_error,
    )


def _evidence_view(
    evidence: Evidence, uploaded: dict[uuid.UUID, date] | None = None
) -> EvidenceView:
    return EvidenceView(
        id=evidence.id,
        source=evidence.source,
        reference=evidence.reference,
        fact=evidence.fact,
        observed_on=evidence.observed_on,
        granularity=evidence.granularity,
        tally=evidence.tally,
        subject=evidence.subject,
        stated_on=(
            (uploaded or {}).get(evidence.resume_file_id)
            if evidence.source is EvidenceSource.RESUME and evidence.resume_file_id
            else None
        ),
    )


def get_newest_first(evidence: Iterable[EvidenceView]) -> tuple[EvidenceView, ...]:
    """Newest first by the date each fact is shown with, undated last; ties by
    source, then id, so the order is the same every time. Pure."""

    def order(e: EvidenceView) -> tuple[bool, int, str, str]:
        shown = e.shown_on
        return (shown is None, -shown.toordinal() if shown else 0, str(e.source), str(e.id))

    return tuple(sorted(evidence, key=order))


async def _upload_dates(mine: OwnerProfile) -> dict[uuid.UUID, date]:
    """The day each of the user's résumé files was uploaded: what a résumé
    line is dated by. One user's uploads: a handful."""
    return {
        r.id: r.created_at.date()
        for r in await mine.resumes.get_list(ResumeFileFilter())
        if r.created_at is not None
    }


def _resume_view(resume: ResumeFile) -> ResumeFileView:
    # Set by the database when the upload was stored; always present on a read.
    assert resume.created_at is not None, "a stored resume has an upload time"
    return ResumeFileView(
        id=resume.id,
        filename=resume.filename,
        status=str(resume.status),
        parse_error=resume.parse_error,
        uploaded_at=resume.created_at,
    )


def _answer_ref(question_id: str) -> str:
    return f"answer:{question_id}"
