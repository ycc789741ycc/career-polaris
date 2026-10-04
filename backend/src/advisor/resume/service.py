"""The Resume Advisor: one résumé per Target, written from cited evidence.

* A résumé is requested in the api and its first version written by a worker
  job on the user's key; the row exists from the request with a status the page
  polls (ADR 0006).
* Versions are never overwritten. A manual save, a generated draft and an edit
  applied from the chat each add one.
* The revision chat streams from the api: prose as it arrives, then a proposed
  revision the user applies or ignores (ADR 0007 is about export; the chat is
  ``AiGateway.stream_structured``).
* Export renders a version to PDF on the worker's ``docs`` queue and hands back
  a short-lived signed link that downloads the file. An export of a version,
  look and trim already rendered is reused (ADR 0038, ADR 0040).
* A résumé is written again only when the user asks. It records what its latest
  generated version read, and says it is outdated once the evidence or the
  Target has moved on (ADR 0035).
* A résumé is set in a built-in template or in one of the user's own: a name
  and a checked ``TemplateSpec``, never markup (ADR 0040).
* A template can start from a PDF: the worker reads its style locally into a
  draft spec, deletes the file, and keeps nothing of its text (ADR 0041).

Every line the model writes must cite Evidence the user owns; a reply that
does not is rejected as a whole. Coverage of the Target's requirements is
computed from scores, not written by the model.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from advisor.assessment import AssessmentService
from advisor.profile import (
    CitationError,
    CitationHandles,
    ProfileService,
    ProfileSnapshot,
    assert_citations_exist,
    get_evidence_line,
)
from advisor.resume.domain import (
    BUILT_IN_TEMPLATES,
    DEFAULT_PLAN,
    MAX_BULLETS_PER_ROLE,
    MAX_ROLES,
    MAX_SKILLS,
    TRIMMED_BULLETS,
    TRIMMED_SKILLS,
    BuiltInTemplate,
    Coverage,
    CustomTemplate,
    CustomTemplateFilter,
    Export,
    ExportFilter,
    ExportStatus,
    Options,
    Origin,
    OwnerResumes,
    ReadingStatus,
    ResumeContent,
    ResumeError,
    ResumeStage,
    ResumeStatus,
    ResumeTailored,
    ResumeUnitOfWork,
    ResumeVersion,
    ResumeVersionFilter,
    ResumeVersionSaved,
    Revision,
    RevisionFilter,
    Section,
    SectionKind,
    SectionSlot,
    TailoredResume,
    TailoredResumeFilter,
    Template,
    TemplateReading,
    TemplateReadingError,
    TemplateSpec,
    TemplateSpecError,
    VersionSource,
    assert_plan_valid,
    assert_well_formed,
    assert_written_lines_cited,
    coverage,
    get_download_name,
    get_full_plan,
    get_planned,
    get_proposal_layout,
    get_template_spec_from_runs,
    mark_edits,
    settle_revision,
)
from advisor.resume.domain.constants import (
    BODY_PT_RANGE,
    HEADING_PT_RANGE,
    MAX_HELD_SECTIONS,
    MAX_LINK,
    MAX_SECTION_TITLE,
    MAX_SUMMARY,
    MAX_TEMPLATE_NAME,
    MIN_CONTRAST,
    NAME_PT_RANGE,
    PAGE_HEIGHT_MM,
    PAGE_MARGIN_SIDE_MM,
    PAGE_MARGIN_TOP_MM,
    PAGE_WIDTH_MM,
    RESUME_STAGE_SHARES,
    TEMPLATE_FONTS,
    TEMPLATE_READING_KEEP_SECONDS,
)
from advisor.resume.infra.render import render_html, render_pdf
from advisor.resume.infra.style_reader import read_style_runs
from advisor.target import (
    DraftBasis,
    OutdatedReason,
    TargetRef,
    TargetService,
    TargetSnapshot,
    get_target_digest,
    requirements_block,
)
from kernel.ai_gateway import AiGateway, StreamResult, StreamText
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.documents import PDF_TYPE
from kernel.errors import (
    ConflictError,
    DomainError,
    EvidenceNotOwnedError,
    NotFoundError,
    OutputInvalidError,
    ValidationError,
)
from kernel.logging import get_logger
from kernel.paging import Page, paginate
from kernel.progress import JobCancelledError, Progress, RunningJobView, get_stage_progress
from kernel.storage import ObjectStore, object_key

__all__ = [
    "TEMPLATE_READING_KEEP_SECONDS",
    "CoverageView",
    "ExportView",
    "Options",
    "ResumeService",
    "ResumeSummaryView",
    "ResumeView",
    "RevisionDone",
    "RevisionFailed",
    "RevisionText",
    "RevisionView",
    "SectionKind",
    "SectionSlot",
    "Template",
    "TemplateLimitsView",
    "TemplateReadingView",
    "TemplateView",
    "VersionView",
]

log = get_logger(__name__)

_WRITE = ("resume_write", "v4")
_REVISE = ("resume_revise", "v4")
_SECTION = ("resume_section", "v1")
_MARKER = "<<<PROPOSAL>>>"
# The chat sees this many earlier exchanges, newest last.
_CONVERSATION_TURNS = 6
# Everything the chat reads that a person or a posting wrote.
_REVISE_UNTRUSTED = frozenset({"requirements", "resume", "conversation", "request", "evidence"})
# A custom section's heading is the user's own text.
_SECTION_UNTRUSTED = frozenset({"requirements", "resume", "evidence", "section"})
# The accounts are names a person or a provider chose.
_WRITE_UNTRUSTED = frozenset({"requirements", "evidence", "timeline", "base_resume", "accounts"})


# --- AI output schemas -----------------------------------------------------


class _Bullet(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    answers: str | None = Field(default=None, max_length=400)
    origin: str | None = None


class _Entry(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    org: str = Field(default="", max_length=200)
    when: str = Field(default="", max_length=64)
    link: str = Field(default="", max_length=MAX_LINK)
    bullets: list[_Bullet] = Field(default_factory=list, max_length=MAX_BULLETS_PER_ROLE)


class _Section(BaseModel):
    kind: SectionKind
    title: str | None = Field(default=None, max_length=MAX_SECTION_TITLE)
    text: str = Field(default="", max_length=MAX_SUMMARY)
    entries: list[_Entry] = Field(default_factory=list, max_length=MAX_ROLES)
    items: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)
    bullets: list[_Bullet] = Field(default_factory=list, max_length=MAX_BULLETS_PER_ROLE)
    # Only the chat sets it, and only when asked; None keeps the section's
    # state (ADR 0043).
    is_shown: bool | None = None


class _Resume(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    headline: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=300)
    sections: list[_Section] = Field(default_factory=list, max_length=MAX_HELD_SECTIONS)


class _Proposal(BaseModel):
    changed: bool
    resume: _Resume | None = None


class _SectionReply(BaseModel):
    section: _Section


# --- views -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceNote:
    id: str
    reference: str
    fact: str


@dataclass(frozen=True, slots=True)
class CoverageView:
    requirement: str
    verdict: str
    dimension_key: str | None
    evidence: tuple[EvidenceNote, ...]


@dataclass(frozen=True, slots=True)
class VersionView:
    id: uuid.UUID
    number: int
    label: str
    source: VersionSource
    model_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionView:
    id: uuid.UUID
    request: str
    reply: str
    has_proposal: bool
    applied_version_id: uuid.UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeSummaryView:
    id: uuid.UUID
    target: TargetRef
    label: str
    status: str
    error_code: str | None
    error_message: str | None
    latest_version: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeView:
    summary: ResumeSummaryView
    snapshot: TargetSnapshot | None
    coverage: tuple[CoverageView, ...]
    # The template's id: a built-in one's name, or one of the user's own.
    template: str
    options: Options
    version: VersionView | None
    content: ResumeContent | None
    # Evidence cited anywhere in this version, for the grey notes.
    evidence: dict[str, EvidenceNote]
    versions: tuple[VersionView, ...]
    revisions: tuple[RevisionView, ...]
    # Why the résumé no longer matches what it was last written from (ADR
    # 0035); empty when it does, while it is not ready, and for one written
    # before that was recorded.
    outdated_by: tuple[OutdatedReason, ...] = ()
    # The sections every new version is written to, in order (ADR 0039).
    # While one is being filled it is already here, and empty in the content.
    section_plan: tuple[SectionSlot, ...] = DEFAULT_PLAN

    @property
    def is_outdated(self) -> bool:
        return bool(self.outdated_by)


@dataclass(frozen=True, slots=True)
class ExportView:
    id: uuid.UUID
    version_id: uuid.UUID
    # The built-in template it was rendered in; None for one of the user's own.
    template: Template | None
    status: str
    error_code: str | None
    error_message: str | None
    download_url: str | None


@dataclass(frozen=True, slots=True)
class TemplateView:
    """One template as the PDF renderer draws it: what the preview reads so it
    shows the page the PDF will be (ADR 0038, ADR 0040). Sizes in points, the
    page in millimetres."""

    # A built-in template's name, or the id of one of the user's own.
    id: str
    name: str
    note: str
    is_built_in: bool
    spec: TemplateSpec
    page_width_mm: int
    page_height_mm: int
    margin_top_mm: int
    margin_side_mm: int
    trimmed_bullets: int
    trimmed_skills: int


@dataclass(frozen=True, slots=True)
class TemplateReadingView:
    """A file being read for its style (ADR 0041): once ready, a draft spec
    and which of its values were read from the file and which defaulted."""

    id: uuid.UUID
    status: str
    error_code: str | None
    error_message: str | None
    spec: TemplateSpec | None
    read: tuple[str, ...]
    defaulted: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TemplateLimitsView:
    """What a template of the user's own may set, for the editor."""

    fonts: tuple[str, ...]
    name_pt_range: tuple[float, float]
    heading_pt_range: tuple[float, float]
    body_pt_range: tuple[float, float]
    min_contrast: float
    max_name: int
    max_templates: int
    # A PDF a template may start from.
    upload_max_bytes: int


@dataclass(frozen=True, slots=True)
class RevisionText:
    text: str


@dataclass(frozen=True, slots=True)
class RevisionDone:
    revision_id: uuid.UUID
    reply: str
    # The whole proposed résumé, settled and validated; None for advice only.
    proposal: ResumeContent | None


@dataclass(frozen=True, slots=True)
class RevisionFailed:
    code: str
    message: str


RevisionEvent = RevisionText | RevisionDone | RevisionFailed


# --- service ---------------------------------------------------------------


class ResumeService:
    def __init__(
        self,
        uow: ResumeUnitOfWork,
        *,
        target: TargetService,
        profile: ProfileService,
        assessment: AssessmentService,
        gateway: AiGateway,
        object_store: ObjectStore,
        template_max: int = 10,
        template_upload_max_bytes: int = 5_242_880,
        template_upload_max_pages: int = 3,
    ) -> None:
        self._uow = uow
        self._template_max = template_max
        self._upload_max_bytes = template_upload_max_bytes
        self._upload_max_pages = template_upload_max_pages
        self._target = target
        self._profile = profile
        self._assessment = assessment
        self._gateway = gateway
        self._store = object_store

    # -- writing ------------------------------------------------------------

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        """Priced before anything is spent."""
        preview = await self._target.preview(owner_id, ref)
        profile = await self._profile.snapshot(owner_id)
        estimate = await self._gateway.estimate(
            owner_id,
            task="resume.generate",
            template=load_template(*_WRITE),
            inputs=_write_inputs(
                profile,
                CitationHandles(e.id for e in profile.evidence),
                label=preview.label,
                requirements=preview.requirements_text,
                coverage_rows=(),
                options=Options(),
                base_resume="(read when writing)",
                plan=DEFAULT_PLAN,
            ),
            untrusted=_WRITE_UNTRUSTED,
        )
        return {
            "cost_usd": str(estimate.cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
        }

    async def request(
        self, owner_id: uuid.UUID, ref: TargetRef, *, template: str, options: Options
    ) -> ResumeSummaryView:
        """Record the résumé as drafting; the caller queues ``generate``."""
        preview = await self._target.preview(owner_id, ref)
        async with self._uow.for_owner(owner_id) as mine:
            if any(
                r.is_busy and _ref_of(r) == ref
                for r in await mine.resumes.get_list(TailoredResumeFilter())
            ):
                raise ConflictError("a résumé for this target is already being written")
            built_in, own = await _resolve_template(mine, template)
            resume = await mine.resumes.create(
                TailoredResume.requested(
                    owner_id=owner_id,
                    role_id=ref.role_uuid,
                    job_posting_id=ref.opening_uuid,
                    private_job_posting_id=ref.own_posting_uuid,
                    label=preview.label,
                    template=built_in,
                    custom_template_id=own,
                    options=options,
                    at=utcnow(),
                )
            )
        return _summary(resume, latest_version=None)

    async def redraft(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> ResumeSummaryView:
        """Record the résumé as drafting again; the caller queues ``generate``,
        which saves the result as its next version. Asked for by the user, at a
        price they confirmed (ADR 0035). A résumé still being written is left
        as it is."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            if resume.status is ResumeStatus.DRAFTING:
                raise ConflictError(
                    "this résumé is already being written", resume_id=str(resume_id)
                )
            resume.redraft(utcnow())
            await mine.resumes.update(resume)
            numbers = await mine.versions.latest_numbers()
        return _summary(resume, latest_version=numbers.get(resume_id))

    async def generate(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        """The worker job. An expected failure is recorded on the résumé, with
        its stable code, and not retried on the user's key."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
        if resume.status is not ResumeStatus.DRAFTING:
            return
        ref = _ref_of(resume)
        options = resume.options

        try:
            await self._advance(owner_id, resume_id, ResumeStage.READING)
            await self._generate(owner_id, resume_id, ref, options)
        except JobCancelledError:
            log.info("resume.generate_cancelled", resume_id=str(resume_id))
        except DomainError as exc:
            log.warning("resume.generate_failed", resume_id=str(resume_id), code=str(exc.code))
            await self._fail(owner_id, resume_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fail(
                owner_id,
                resume_id,
                code="internal",
                message="Writing stopped unexpectedly. Try again in a moment.",
            )
            raise

    # -- sections (ADR 0039) ------------------------------------------------

    async def estimate_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> dict[str, Any]:
        """What filling one section from the sources costs, priced first."""
        content, _plan, snapshot = await self._section_context(owner_id, resume_id, slot)
        profile = await self._profile.snapshot(owner_id)
        estimate = await self._gateway.estimate(
            owner_id,
            task="resume.fill_section",
            template=load_template(*_SECTION),
            inputs=_section_inputs(
                profile,
                CitationHandles(e.id for e in profile.evidence),
                snapshot=snapshot,
                content=content,
                slot=slot,
            ),
            untrusted=_SECTION_UNTRUSTED,
        )
        return {
            "cost_usd": str(estimate.cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
        }

    async def request_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> ResumeSummaryView:
        """Show the section, or add one of the user's own, and record it as
        being filled; the caller queues ``fill_section``. A section that
        already has lines, or one the plan has no room for, is refused before
        anything is spent (ADR 0043)."""
        _content, plan, _snapshot = await self._section_context(owner_id, resume_id, slot)
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            now = utcnow()
            resume.update_plan(plan, at=now)
            resume.update_filling(at=now)
            await mine.resumes.update(resume)
            numbers = await mine.versions.latest_numbers()
        return _summary(resume, latest_version=numbers.get(resume_id))

    async def fill_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> None:
        """The worker job: write one section from the sources and save the
        résumé, every other line as it was, as its next version. A section the
        evidence cannot fill is saved empty. A failure leaves the résumé ready,
        with the reason, and is not retried on the user's key."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
        if resume.status is not ResumeStatus.FILLING:
            return
        try:
            await self._advance(owner_id, resume_id, ResumeStage.READING)
            await self._fill_section(owner_id, resume_id, slot)
        except JobCancelledError:
            log.info("resume.fill_section_cancelled", resume_id=str(resume_id))
        except DomainError as exc:
            log.warning("resume.fill_section_failed", resume_id=str(resume_id), code=str(exc.code))
            await self._fill_failed(owner_id, resume_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fill_failed(
                owner_id,
                resume_id,
                code="internal",
                message="Filling the section stopped unexpectedly. Try again in a moment.",
            )
            raise

    async def cancel(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        """Stop the résumé being written, or a section being filled, before its
        next call or its save (ADR 0042). A call already sent is still
        charged. A résumé with a saved version stays on it; a first draft is
        cancelled and no longer listed."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            latest = await _latest_version(mine, resume_id)
            try:
                resume.update_cancelled(
                    latest_plan=(
                        get_full_plan(ResumeContent.from_dict(latest.content).get_plan())
                        if latest
                        else None
                    ),
                    at=utcnow(),
                )
            except ValueError as exc:
                raise ConflictError(str(exc), resume_id=str(resume_id)) from exc
            await mine.resumes.update(resume)
        log.info("resume.cancel_requested", resume_id=str(resume_id))

    async def running_jobs(self, owner_id: uuid.UUID) -> tuple[RunningJobView, ...]:
        """Every résumé being written or having a section filled, for
        ``GET /activity`` (ADR 0042)."""
        async with self._uow.for_owner(owner_id) as mine:
            resumes = await mine.resumes.get_list(TailoredResumeFilter())
        return tuple(
            RunningJobView(
                kind="section" if r.status is ResumeStatus.FILLING else "resume",
                id=str(r.id),
                role_id=str(r.role_id) if r.role_id else None,
                job_posting_id=str(r.job_posting_id) if r.job_posting_id else None,
                private_job_posting_id=(
                    str(r.private_job_posting_id) if r.private_job_posting_id else None
                ),
                label=r.target_label,
                stage=str(r.stage) if r.stage else None,
                progress=r.progress,
                started_at=r.updated_at,
                estimated_cost_usd=r.estimated_cost_usd,
            )
            for r in resumes
            if r.is_busy
        )

    # -- reading ------------------------------------------------------------

    async def saved(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[ResumeSummaryView]:
        """Saved résumés, most recently changed first. One user's résumés, read
        whole, so the change order is applied here — and the page cut after it —
        rather than by the store, which orders by creation."""
        async with self._uow.for_owner(owner_id) as mine:
            resumes = await mine.resumes.get_list(TailoredResumeFilter())
            numbers = await mine.versions.latest_numbers()
        views = [
            _summary(r, latest_version=numbers.get(r.id))
            for r in sorted(resumes, key=lambda r: (r.updated_at, r.id), reverse=True)
            if r.is_shown
        ]
        return paginate(views, page, page_size)

    async def get(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, number: int | None = None
    ) -> ResumeView:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            versions = sorted(
                await mine.versions.get_list(ResumeVersionFilter(resume_id=resume_id)),
                key=lambda v: v.number,
                reverse=True,
            )
            # The chat reads oldest first.
            revisions = list(
                reversed(await mine.revisions.get_list(RevisionFilter(resume_id=resume_id)))
            )

        chosen = (
            next((v for v in versions if v.number == number), None)
            if number is not None
            else (versions[0] if versions else None)
        )
        if number is not None and chosen is None:
            raise NotFoundError("version not found", number=number)
        content = ResumeContent.from_dict(chosen.content) if chosen else None
        if content is not None and number is None:
            # The latest, laid out as the plan, holding every section: a
            # section being filled shows, empty, where it will go.
            content = get_planned(content, get_full_plan(resume.section_plan))
        notes = await self._notes(owner_id, content.cited() if content else set())
        outdated_by = (
            await self._target.get_outdated_reasons(
                owner_id,
                _ref_of(resume),
                recorded=_basis_of(resume),
                profile_version=await self._profile.version(owner_id),
            )
            if resume.status is ResumeStatus.READY
            else ()
        )
        return ResumeView(
            summary=_summary(resume, latest_version=versions[0].number if versions else None),
            snapshot=TargetSnapshot.from_dict(resume.snapshot) if resume.snapshot else None,
            coverage=tuple(_coverage_view(c) for c in resume.coverage),
            template=_template_id(resume),
            options=resume.options,
            version=_version_view(chosen) if chosen else None,
            content=content,
            evidence=notes,
            versions=tuple(_version_view(v) for v in versions),
            revisions=tuple(_revision_view(r) for r in revisions),
            outdated_by=outdated_by,
            section_plan=get_full_plan(resume.section_plan),
        )

    # -- editing ------------------------------------------------------------

    async def update_settings(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        template: str,
        options: Options,
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            built_in, own = await _resolve_template(mine, template)
            resume.restyle(template=built_in, custom_template_id=own, options=options, at=utcnow())
            await mine.resumes.update(resume)

    async def save_version(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        content: dict[str, Any],
        label: str | None = None,
    ) -> VersionView:
        """Save the user's edits as a new version.

        A line they changed is theirs and may stand uncited; a line they left
        alone keeps what it cited. Anything cited must still be their evidence.
        """
        try:
            edited = ResumeContent.from_dict(content)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError(f"that résumé could not be read: {exc}") from exc
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            latest = await _latest_version(mine, resume_id)
            previous = ResumeContent.from_dict(latest.content) if latest else None
        settled = mark_edits(previous, edited)
        try:
            assert_well_formed(settled)
        except ResumeError as exc:
            raise ValidationError(str(exc)) from exc
        await self._assert_owned(owner_id, settled, "your edit cites evidence that is not yours")
        return await self._add_version(
            owner_id,
            resume_id,
            content=settled,
            source=VersionSource.MANUAL,
            label=label or f"{resume.target_label} — edited",
            model_id=None,
            template_version=None,
        )

    async def revise(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        request: str,
        content: dict[str, Any],
    ) -> AsyncIterator[RevisionEvent]:
        """One exchange in the revision chat, streamed.

        Prose arrives as ``RevisionText``; the exchange ends with
        ``RevisionDone`` carrying a validated proposal, or ``RevisionFailed``
        with the error's stable code. Nothing is applied until the user says so.
        """
        try:
            current = ResumeContent.from_dict(content)
            assert_well_formed(current)
            async with self._uow.for_owner(owner_id) as mine:
                resume = await _owned(mine, resume_id)
                if resume.snapshot is None:
                    raise ValidationError("this résumé has not been written yet")
                snapshot = TargetSnapshot.from_dict(resume.snapshot)
                coverage_rows = [_coverage_view(c) for c in resume.coverage]
                earlier = await mine.revisions.get_list(
                    RevisionFilter(resume_id=resume_id), page_size=_CONVERSATION_TURNS
                )
            profile = await self._profile.snapshot(owner_id)
            handles = CitationHandles(e.id for e in profile.evidence)
            shown = current.with_citations(lambda ids: tuple(handles.handle(i) for i in ids))
            inputs = {
                "target": snapshot.label,
                "requirements": requirements_block(snapshot),
                "coverage": _coverage_block(coverage_rows),
                "resume": json.dumps(shown.to_dict(), ensure_ascii=False),
                "conversation": "\n".join(
                    f"Person: {r.request}\nYou: {r.reply}" for r in reversed(earlier)
                )
                or "(this is the first message)",
                "request": request,
                "evidence": _evidence_block(profile.evidence, handles),
            }

            reply_parts: list[str] = []
            result: StreamResult[_Proposal] | None = None
            async for event in self._gateway.stream_structured(
                owner_id,
                task="resume.revise",
                template=load_template(*_REVISE),
                inputs=inputs,
                output_schema=_Proposal,
                marker=_MARKER,
                untrusted=_REVISE_UNTRUSTED,
            ):
                if isinstance(event, StreamText):
                    reply_parts.append(event.text)
                    yield RevisionText(event.text)
                else:
                    result = event
            if result is None:
                raise OutputInvalidError("the reply ended without a proposal")

            proposal: ResumeContent | None = None
            if result.value.changed and result.value.resume is not None:
                message = "the proposed revision cited evidence that is not yours"
                written = result.value.resume
                try:
                    proposal = settle_revision(
                        current,
                        get_proposal_layout(
                            current,
                            _content_of(written),
                            [s.is_shown for s in written.sections],
                        ),
                        handles.resolve,
                    )
                except CitationError as exc:
                    raise EvidenceNotOwnedError(message, invented=sorted(exc.invented)) from exc
                try:
                    assert_well_formed(proposal)
                    assert_written_lines_cited(proposal)
                except ResumeError as exc:
                    raise OutputInvalidError(f"the proposed revision was rejected: {exc}") from exc
                await self._assert_owned(owner_id, proposal, message)

            reply = "".join(reply_parts).strip()
            async with self._uow.for_owner(owner_id) as mine:
                revision = await mine.revisions.create(
                    Revision(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        resume_id=resume_id,
                        request=request,
                        reply=reply,
                        proposal=proposal.to_dict() if proposal else None,
                        model_id=result.model_id,
                        template_version=result.template_version,
                        created_at=utcnow(),
                    )
                )
            yield RevisionDone(revision_id=revision.id, reply=reply, proposal=proposal)
        except DomainError as exc:
            # The response is already streaming, so the failure travels as the
            # last event, in the same {code, message} terms as any error.
            log.warning("resume.revise_failed", resume_id=str(resume_id), code=str(exc.code))
            yield RevisionFailed(code=str(exc.code), message=exc.message)

    async def apply_revision(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, revision_id: uuid.UUID
    ) -> VersionView:
        """An accepted chat edit becomes a version (architecture §6)."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            revision = await mine.revisions.get(revision_id)
            if revision is None or revision.resume_id != resume_id:
                raise NotFoundError("revision not found", revision_id=str(revision_id))
            if revision.proposal is None:
                raise ValidationError("that reply proposed no change to apply")
            if revision.applied_version_id is not None:
                raise ValidationError("that revision has already been applied")
            proposal = ResumeContent.from_dict(revision.proposal)
            model_id, template_version = revision.model_id, revision.template_version
            label = resume.target_label
        version = await self._add_version(
            owner_id,
            resume_id,
            content=proposal,
            source=VersionSource.CHAT,
            label=f"{label} — revised",
            model_id=model_id,
            template_version=template_version,
        )
        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.revisions.get(revision_id)
            if stored is not None:
                stored.applied_version_id = version.id
                await mine.revisions.update(stored)
        return version

    # -- templates ----------------------------------------------------------

    async def templates(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[TemplateView]:
        """Every template the user can choose, as the renderer draws it: the
        built-in ones, then their own, oldest first."""
        async with self._uow.for_owner(owner_id) as mine:
            own = await mine.templates.get_list(CustomTemplateFilter())
        views = [_built_in_view(t) for t in BUILT_IN_TEMPLATES.values()]
        views += [_own_view(t) for t in reversed(own)]
        return paginate(views, page, page_size)

    def template_limits(self) -> TemplateLimitsView:
        return TemplateLimitsView(
            fonts=TEMPLATE_FONTS,
            name_pt_range=NAME_PT_RANGE,
            heading_pt_range=HEADING_PT_RANGE,
            body_pt_range=BODY_PT_RANGE,
            min_contrast=MIN_CONTRAST,
            max_name=MAX_TEMPLATE_NAME,
            max_templates=self._template_max,
            upload_max_bytes=self._upload_max_bytes,
        )

    async def create_template(
        self, owner_id: uuid.UUID, *, name: str, spec: dict[str, Any]
    ) -> TemplateView:
        """Keep a template of the user's own, up to ``template_max`` of them."""
        async with self._uow.for_owner(owner_id) as mine:
            if await mine.templates.get_count(CustomTemplateFilter()) >= self._template_max:
                raise ConflictError(
                    f"you can keep {self._template_max} templates of your own;"
                    " delete one to make another"
                )
            try:
                template = CustomTemplate.create(
                    owner_id=owner_id, name=name, spec=TemplateSpec.from_dict(spec), at=utcnow()
                )
            except TemplateSpecError as exc:
                raise ValidationError(str(exc)) from exc
            await mine.templates.create(template)
        return _own_view(template)

    async def update_template(
        self, owner_id: uuid.UUID, template_id: uuid.UUID, *, name: str, spec: dict[str, Any]
    ) -> TemplateView:
        """Change a template of the user's own. Résumés set in it take the new
        look; a PDF already exported keeps the look it was rendered in."""
        async with self._uow.for_owner(owner_id) as mine:
            template = await _owned_template(mine, template_id)
            try:
                template.update_design(name=name, spec=TemplateSpec.from_dict(spec), at=utcnow())
            except TemplateSpecError as exc:
                raise ValidationError(str(exc)) from exc
            await mine.templates.update(template)
        return _own_view(template)

    async def delete_template(self, owner_id: uuid.UUID, template_id: uuid.UUID) -> None:
        """Delete a template of the user's own; résumés set in it go back to
        Organic, the default."""
        async with self._uow.for_owner(owner_id) as mine:
            template = await _owned_template(mine, template_id)
            for resume in await mine.resumes.get_list(
                TailoredResumeFilter(custom_template_id=template_id)
            ):
                resume.restyle(template=Template.ORGANIC, options=resume.options, at=utcnow())
                await mine.resumes.update(resume)
            await mine.templates.delete(template.id)

    # -- a template from a file (ADR 0041) -------------------------------------

    async def upload_template_file(
        self, owner_id: uuid.UUID, *, content_type: str, content: bytes
    ) -> TemplateReadingView:
        """Store a PDF to read a template's style from, and record the reading;
        the caller queues ``read_template``. Nothing is read here. A Word file
        has no fixed layout to read, so only a PDF is taken."""
        if len(content) > self._upload_max_bytes:
            raise ValidationError(
                "this file is larger than we accept", limit_bytes=self._upload_max_bytes
            )
        if content_type != PDF_TYPE:
            raise ValidationError("a template can start only from a PDF", content_type=content_type)
        if not content.strip():
            raise ValidationError("this file is empty")
        key = object_key(owner_id, "templatefiles", str(uuid.uuid4()))
        reading = TemplateReading.create(owner_id=owner_id, storage_key=key, at=utcnow())
        self._store.put(key, content, content_type)
        async with self._uow.for_owner(owner_id) as mine:
            await mine.readings.create(reading)
        log.info("resume.template_file_uploaded", template_reading_id=str(reading.id))
        return _reading_view(reading)

    async def read_template(self, owner_id: uuid.UUID, reading_id: uuid.UUID) -> None:
        """The worker ``docs`` job: read the file's style into a draft, then
        delete the file whether that worked or not. A file with no style to
        read is recorded as ``unreadable_file``."""
        async with self._uow.for_owner(owner_id) as mine:
            reading = await mine.readings.get(reading_id)
        if reading is None or reading.status is not ReadingStatus.READING:
            return
        key = reading.storage_key
        try:
            if key is None:
                raise TemplateReadingError("the file is gone")
            runs, width = read_style_runs(self._store.get(key), max_pages=self._upload_max_pages)
            reading.update_read(get_template_spec_from_runs(runs, page_width=width), at=utcnow())
        except (TemplateReadingError, ValidationError) as exc:
            reading.update_failed(code="unreadable_file", message=str(exc), at=utcnow())
        except Exception:
            reading.update_failed(
                code="internal", message="Reading stopped unexpectedly.", at=utcnow()
            )
            raise
        finally:
            if key is not None:
                self._store.delete(key)
            async with self._uow.for_owner(owner_id) as mine:
                await mine.readings.update(reading)
        log.info(
            "resume.template_file_read",
            template_reading_id=str(reading_id),
            status=str(reading.status),
        )

    async def template_reading(
        self, owner_id: uuid.UUID, reading_id: uuid.UUID
    ) -> TemplateReadingView:
        async with self._uow.for_owner(owner_id) as mine:
            reading = await mine.readings.get(reading_id)
        if reading is None:
            raise NotFoundError("template reading not found", template_reading_id=str(reading_id))
        return _reading_view(reading)

    async def forget_template_reading(self, owner_id: uuid.UUID, reading_id: uuid.UUID) -> None:
        """The draft a day on: deleted, with the file if it is somehow still
        there. Saving it as a template never needed the reading."""
        async with self._uow.for_owner(owner_id) as mine:
            reading = await mine.readings.get(reading_id)
            if reading is None:
                return
            if reading.storage_key is not None:
                self._store.delete(reading.storage_key)
            await mine.readings.delete(reading.id)

    # -- export -------------------------------------------------------------

    async def request_export(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, number: int
    ) -> ExportView:
        """Record an export of one version, in the résumé's look and trim as
        they are now; the caller queues ``export`` while it is rendering.

        An export of the same version, look and trim already rendered is
        returned as it is, and nothing is rendered again (ADR 0038). The look
        is compared as a spec, so a template edited since renders again
        (ADR 0040).
        """
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            found = await mine.versions.get_list(
                ResumeVersionFilter(resume_id=resume_id, number=number), page_size=1
            )
            if not found:
                raise NotFoundError("version not found", number=number)
            spec = (await _spec_of(mine, resume)).to_dict()
            same = ExportFilter(
                version_id=found[0].id, trim=resume.options.trim, status=ExportStatus.READY
            )
            for rendered in await mine.exports.get_list(same):
                if rendered.spec == spec:
                    return _export_view(rendered, download_url=None)
            export = await mine.exports.create(
                Export(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    version_id=found[0].id,
                    template=resume.template,
                    spec=spec,
                    trim=resume.options.trim,
                    status=ExportStatus.RENDERING,
                    created_at=utcnow(),
                )
            )
        return _export_view(export, download_url=None)

    async def export(self, owner_id: uuid.UUID, export_id: uuid.UUID) -> None:
        """The worker ``docs`` job: render, store, done. Failures are recorded."""
        async with self._uow.for_owner(owner_id) as mine:
            export = await mine.exports.get(export_id)
            if export is None:
                raise NotFoundError("export not found", export_id=str(export_id))
            if export.status is not ExportStatus.RENDERING:
                return
            version = await mine.versions.get(export.version_id)
            if version is None:
                raise NotFoundError("version not found", version_id=str(export.version_id))
            resume = await mine.resumes.get(version.resume_id)
            if resume is None:
                raise NotFoundError("résumé not found", resume_id=str(version.resume_id))
            content = ResumeContent.from_dict(version.content)
            # The look asked for when Export was clicked; an export from before
            # it was kept is drawn in its built-in template.
            spec = (
                TemplateSpec.from_dict(export.spec)
                if export.spec is not None
                else BUILT_IN_TEMPLATES[export.template or Template.ORGANIC].spec
            )
            # The trim asked for when Export was clicked, not whatever it is now.
            options = (
                resume.options
                if export.trim is None
                else Options(
                    metrics=resume.options.metrics,
                    reorder=resume.options.reorder,
                    trim=export.trim,
                )
            )

        try:
            pdf = render_pdf(render_html(content, spec=spec, options=options))
        except (ValueError, OSError) as exc:
            await self._fail_export(
                owner_id,
                export_id,
                code="render_failed",
                message=f"The PDF could not be rendered: {exc}",
            )
            log.warning("resume.export_failed", export_id=str(export_id))
            return
        except Exception:
            await self._fail_export(
                owner_id, export_id, code="internal", message="Rendering stopped unexpectedly."
            )
            raise

        key = object_key(owner_id, "exports", f"{export_id}.pdf")
        self._store.put(key, pdf, "application/pdf")
        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.exports.get(export_id)
            if stored is not None:
                stored.rendered(key, at=utcnow())
                await mine.exports.update(stored)

    async def get_export(self, owner_id: uuid.UUID, export_id: uuid.UUID) -> ExportView:
        """The export, and once it is ready a link that downloads it, signed
        now, saved as "<name> — <role>.pdf" (ADR 0038)."""
        async with self._uow.for_owner(owner_id) as mine:
            export = await mine.exports.get(export_id)
            if export is None:
                raise NotFoundError("export not found", export_id=str(export_id))
            if export.storage_key is None:
                return _export_view(export, download_url=None)
            version = await mine.versions.get(export.version_id)
            resume = await mine.resumes.get(version.resume_id) if version else None
        name = get_download_name(
            str((version.content if version else {}).get("name", "")),
            resume.target_label if resume else "",
        )
        url = self._store.signed_url(export.storage_key, download_name=name)
        return _export_view(export, download_url=url)

    # -- internals ----------------------------------------------------------

    async def _generate(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        ref: TargetRef,
        options: Options,
    ) -> None:
        snapshot = await self._target.snapshot(owner_id, ref)
        coverage_rows = await self._coverage(owner_id, snapshot)
        base = await self._profile.base_resume_text(owner_id)
        profile = await self._profile.snapshot(owner_id)
        handles = CitationHandles(e.id for e in profile.evidence)
        async with self._uow.for_owner(owner_id) as mine:
            # Every section, shown or not; one written before a résumé held
            # them all takes the kinds it lacks, hidden (ADR 0043).
            plan = get_full_plan((await _owned(mine, resume_id)).section_plan)
        result = await self._gateway.run(
            owner_id,
            on_progress=self._writing(owner_id, resume_id),
            task="resume.generate",
            template=load_template(*_WRITE),
            inputs=_write_inputs(
                profile,
                handles,
                label=snapshot.label,
                requirements=requirements_block(snapshot),
                coverage_rows=coverage_rows,
                options=options,
                base_resume=base or "(none uploaded)",
                plan=plan,
            ),
            output_schema=_Resume,
            untrusted=_WRITE_UNTRUSTED,
        )
        await self._advance(owner_id, resume_id, ResumeStage.CHECKING)
        message = "the résumé cited evidence that is not yours"
        try:
            # Written to the plan: its sections, in its order, each shown or
            # hidden as it was, and no others.
            content = get_planned(_content_of(result.value), plan).with_citations(handles.resolve)
        except CitationError as exc:
            raise EvidenceNotOwnedError(message, invented=sorted(exc.invented)) from exc
        try:
            assert_well_formed(content)
            assert_written_lines_cited(content)
        except ResumeError as exc:
            raise OutputInvalidError(f"the written résumé was rejected: {exc}") from exc
        await self._assert_owned(owner_id, content, message)
        await self._advance(owner_id, resume_id, ResumeStage.SAVING)

        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            if resume.status is not ResumeStatus.DRAFTING:
                # Cancelled at the last moment: nothing of it is saved.
                raise JobCancelledError
            resume.written(
                snapshot=snapshot.to_dict(),
                label=snapshot.label,
                coverage=tuple(_coverage_dict(c) for c in coverage_rows),
                profile_version=profile.version,
                target_digest=get_target_digest(snapshot),
                at=utcnow(),
            )
            await mine.resumes.update(resume)
            label = resume.target_label
        await self._add_version(
            owner_id,
            resume_id,
            content=content,
            source=VersionSource.GENERATED,
            label=label,
            model_id=result.model_id,
            template_version=result.template_version,
        )
        async with self._uow.for_owner(owner_id) as mine:
            mine.record(
                ResumeTailored(owner_id=owner_id, resume_id=resume_id, role_id=ref.role_uuid)
            )

    async def _section_context(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> tuple[ResumeContent, tuple[SectionSlot, ...], TargetSnapshot]:
        """The résumé as it stands, the plan with ``slot`` shown — in its
        place, or added at the end — and the Target. Only an empty section is
        filled: one written since ADR 0043 that the evidence left empty, one
        of an older résumé, or a new one of the user's own. Refuses a section
        the résumé cannot take."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            latest = await _latest_version(mine, resume_id)
        if resume.status is not ResumeStatus.READY or latest is None or resume.snapshot is None:
            raise ConflictError(
                "this résumé is not ready to take a section", resume_id=str(resume_id)
            )
        content = ResumeContent.from_dict(latest.content)
        held = get_full_plan(content.get_plan())
        existing = content.get_section(slot)
        if existing is not None and not existing.is_empty:
            raise ValidationError("that section already has lines: show it, or edit it in place")
        plan = (
            tuple(s.update_shown(True) if s == slot else s for s in held)
            if slot in held
            else (*held, slot.update_shown(True))
        )
        try:
            assert_plan_valid(plan)
        except ResumeError as exc:
            raise ValidationError(str(exc)) from exc
        return content, plan, TargetSnapshot.from_dict(resume.snapshot)

    async def _fill_section(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, slot: SectionSlot
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            latest = await _latest_version(mine, resume_id)
        if latest is None or resume.snapshot is None:
            raise ConflictError("this résumé has nothing to add a section to")
        current = get_planned(ResumeContent.from_dict(latest.content), resume.section_plan)
        profile = await self._profile.snapshot(owner_id)
        handles = CitationHandles(e.id for e in profile.evidence)
        result = await self._gateway.run(
            owner_id,
            on_progress=self._writing(owner_id, resume_id),
            task="resume.fill_section",
            template=load_template(*_SECTION),
            inputs=_section_inputs(
                profile,
                handles,
                snapshot=TargetSnapshot.from_dict(resume.snapshot),
                content=current,
                slot=slot,
            ),
            output_schema=_SectionReply,
            untrusted=_SECTION_UNTRUSTED,
        )
        await self._advance(owner_id, resume_id, ResumeStage.CHECKING)
        message = "the section cited evidence that is not yours"
        written = _section_of(result.value.section)
        if written.kind is not slot.kind:
            raise OutputInvalidError("the reply wrote a different section than was asked for")
        try:
            # The slot's own heading, whatever the reply called it.
            written = replace(written, title=slot.title, is_shown=True).update_bullets(
                lambda b: replace(b, evidence_ids=handles.resolve(b.evidence_ids))
            )
        except CitationError as exc:
            raise EvidenceNotOwnedError(message, invented=sorted(exc.invented)) from exc
        content = replace(
            current,
            sections=tuple(written if s.slot == slot else s for s in current.sections),
        )
        try:
            assert_well_formed(content)
            assert_written_lines_cited(content)
        except ResumeError as exc:
            raise OutputInvalidError(f"the written section was rejected: {exc}") from exc
        await self._assert_owned(owner_id, content, message)
        await self._advance(owner_id, resume_id, ResumeStage.SAVING)
        await self._add_version(
            owner_id,
            resume_id,
            content=content,
            source=VersionSource.GENERATED,
            while_busy=True,
            label=f"{resume.target_label} — {written.heading} filled"[:200],
            model_id=result.model_id,
            template_version=result.template_version,
        )
        async with self._uow.for_owner(owner_id) as mine:
            stored = await _owned(mine, resume_id)
            stored.update_filled(at=utcnow())
            await mine.resumes.update(stored)

    def _writing(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID
    ) -> Callable[[Progress], Awaitable[None]]:
        async def report(progress: Progress) -> None:
            await self._advance(
                owner_id,
                resume_id,
                ResumeStage.WRITING,
                fraction=progress.fraction,
                cost=progress.estimated_cost_usd,
            )

        return report

    async def _advance(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        stage: ResumeStage,
        *,
        fraction: float = 0.0,
        cost: Decimal | None = None,
    ) -> None:
        """Record the stage the job on the résumé has reached, unless it was
        cancelled, which stops it here: before a call, or while one streams."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            if not resume.is_busy:
                raise JobCancelledError
            resume.update_stage(
                stage,
                progress=get_stage_progress(RESUME_STAGE_SHARES, str(stage), fraction),
                cost=cost,
            )
            await mine.resumes.update(resume)

    async def _fill_failed(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
            if resume is not None and resume.status is ResumeStatus.FILLING:
                resume.update_fill_failed(code=code, message=message, at=utcnow())
                await mine.resumes.update(resume)

    async def _coverage(
        self, owner_id: uuid.UUID, snapshot: TargetSnapshot
    ) -> tuple[CoverageView, ...]:
        assessment = await self._assessment.latest(owner_id)
        dimensions = assessment.dimensions if assessment else ()
        rows = coverage(
            requirements=[r.statement for r in snapshot.requirements],
            requirement_map=snapshot.requirement_map,
            scores={d.key: d.score for d in dimensions},
            targets={d.dimension_key: d.target_score for d in snapshot.dimensions},
            evidence={d.key: d.evidence_ids for d in dimensions},
        )
        notes = await self._notes(owner_id, {i for row in rows for i in row.evidence_ids})
        return tuple(_coverage_row(row, notes) for row in rows)

    async def _assert_owned(
        self, owner_id: uuid.UUID, content: ResumeContent, message: str
    ) -> None:
        owned = await self._profile.evidence_ids(owner_id)
        try:
            assert_citations_exist(content.cited(), owned)
        except CitationError as exc:
            # An invented citation is how a fabricated claim gets in.
            raise EvidenceNotOwnedError(message, invented=sorted(exc.invented)) from exc

    async def _notes(self, owner_id: uuid.UUID, ids: set[str]) -> dict[str, EvidenceNote]:
        if not ids:
            return {}
        profile = await self._profile.snapshot(owner_id)
        return {
            str(e.id): EvidenceNote(str(e.id), e.reference, e.fact)
            for e in profile.evidence
            if str(e.id) in ids
        }

    async def _add_version(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        content: ResumeContent,
        source: VersionSource,
        label: str,
        model_id: str | None,
        template_version: str | None,
        while_busy: bool = False,
    ) -> VersionView:
        """Save the next version. ``while_busy`` is a job's save: one whose
        job was cancelled meanwhile saves nothing."""
        now = utcnow()
        async with self._uow.for_owner(owner_id) as mine:
            resume = await _owned(mine, resume_id)
            if while_busy and not resume.is_busy:
                raise JobCancelledError
            latest = await _latest_version(mine, resume_id)
            version = await mine.versions.create(
                ResumeVersion(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    resume_id=resume_id,
                    number=(latest.number if latest else 0) + 1,
                    label=label[:200],
                    content=content.to_dict(),
                    source=source,
                    model_id=model_id,
                    template_version=template_version,
                    created_at=now,
                )
            )
            resume.touched(now)
            # Every version is written to the plan, or changes it: a section
            # shown, hidden, added, removed or moved, by hand or in the chat
            # (ADR 0039). The plan holds every built-in kind (ADR 0043).
            resume.update_plan(get_full_plan(content.get_plan()), at=now)
            await mine.resumes.update(resume)
            mine.record(
                ResumeVersionSaved(
                    owner_id=owner_id, resume_id=resume_id, number=version.number, source=source
                )
            )
            return _version_view(version)

    async def _fail_export(
        self, owner_id: uuid.UUID, export_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.exports.get(export_id)
            if stored is not None:
                stored.failed(code=code, message=message, at=utcnow())
                await mine.exports.update(stored)

    async def _fail(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
            if resume is not None:
                resume.failed(code=code, message=message, at=utcnow())
                await mine.resumes.update(resume)


# --- helpers ---------------------------------------------------------------


async def _owned(mine: OwnerResumes, resume_id: uuid.UUID) -> TailoredResume:
    resume = await mine.resumes.get(resume_id)
    if resume is None:
        raise NotFoundError("résumé not found", resume_id=str(resume_id))
    return resume


async def _latest_version(mine: OwnerResumes, resume_id: uuid.UUID) -> ResumeVersion | None:
    """Versions are added one at a time, so the newest is the highest number."""
    found = await mine.versions.get_list(ResumeVersionFilter(resume_id=resume_id), page_size=1)
    return found[0] if found else None


def _content_of(model: _Resume) -> ResumeContent:
    return ResumeContent(
        name=model.name,
        headline=model.headline,
        contact=model.contact,
        sections=tuple(_section_of(s) for s in model.sections),
    )


def _section_of(model: _Section) -> Section:
    data = model.model_dump(mode="json")
    # Laid out by the plan, or by the chat's proposal, once read.
    data["is_shown"] = True
    for line in (*data["bullets"], *(b for e in data["entries"] for b in e["bullets"])):
        # The model writes; it does not get to say otherwise.
        line["origin"] = str(Origin.WRITTEN)
    return Section.from_dict(data)


def _plan_lines(plan: tuple[SectionSlot, ...]) -> str:
    """The sections to write, in order, as the prompts name them: all of
    them, shown or not, since a hidden one may be shown later."""
    return "\n".join(f"- {slot.kind}" + (f": {slot.title}" if slot.title else "") for slot in plan)


def _ref_of(resume: TailoredResume) -> TargetRef:
    return TargetRef.of(resume.role_id, resume.job_posting_id, resume.private_job_posting_id)


def _basis_of(resume: TailoredResume) -> DraftBasis | None:
    """What the latest generated version read; None for a résumé written
    before it was kept."""
    if resume.profile_version is None or resume.target_digest is None:
        return None
    return DraftBasis(profile_version=resume.profile_version, target_digest=resume.target_digest)


def _write_inputs(
    profile: ProfileSnapshot,
    handles: CitationHandles,
    *,
    label: str,
    requirements: str,
    coverage_rows: tuple[CoverageView, ...] | list[CoverageView],
    options: Options,
    base_resume: str,
    plan: tuple[SectionSlot, ...],
) -> dict[str, str]:
    timeline = "\n".join(
        f"- {p.title} at {p.company}, {p.started_on} to {p.ended_on or 'present'}"
        for p in profile.positions
    )
    accounts = "\n".join(f"- {a.source}: {a.account}" for a in profile.accounts)
    return {
        "target": label,
        "requirements": requirements,
        "coverage": _coverage_block(coverage_rows) or "(worked out when writing)",
        "options": "\n".join(
            line
            for line, wanted in (
                ("- Quantify bullets with numbers the evidence gives.", options.metrics),
                ("- Order skills by what this job screens for.", options.reorder),
                ("- Keep it to one page: at most 3 bullets a role.", options.trim),
            )
            if wanted
        )
        or "- No special instructions.",
        "timeline": timeline or "(no positions recorded)",
        "accounts": accounts or "(none connected)",
        "base_resume": base_resume,
        "sections": _plan_lines(plan),
        "evidence": _evidence_block(profile.evidence, handles),
    }


def _section_inputs(
    profile: ProfileSnapshot,
    handles: CitationHandles,
    *,
    snapshot: TargetSnapshot,
    content: ResumeContent,
    slot: SectionSlot,
) -> dict[str, str]:
    shown = content.with_citations(lambda ids: tuple(handles.handle(i) for i in ids))
    return {
        "target": snapshot.label,
        "requirements": requirements_block(snapshot),
        "section": str(slot.kind) + (f": {slot.title}" if slot.title else ""),
        "resume": json.dumps(shown.to_dict(), ensure_ascii=False),
        "evidence": _evidence_block(profile.evidence, handles),
    }


def _evidence_block(evidence: Any, handles: CitationHandles) -> str:
    return (
        "\n".join(get_evidence_line(e, handles.handle(e.id)) for e in evidence) or "(no evidence)"
    )


def _coverage_row(row: Coverage, notes: dict[str, EvidenceNote]) -> CoverageView:
    return CoverageView(
        requirement=row.requirement,
        verdict=str(row.verdict),
        dimension_key=row.dimension_key,
        evidence=tuple(notes[i] for i in row.evidence_ids if i in notes),
    )


def _coverage_dict(row: CoverageView) -> dict[str, Any]:
    return {
        "requirement": row.requirement,
        "verdict": row.verdict,
        "dimension_key": row.dimension_key,
        "evidence": [{"id": e.id, "reference": e.reference, "fact": e.fact} for e in row.evidence],
    }


def _coverage_view(data: dict[str, Any]) -> CoverageView:
    return CoverageView(
        requirement=data["requirement"],
        verdict=data["verdict"],
        dimension_key=data.get("dimension_key"),
        evidence=tuple(EvidenceNote(**e) for e in data.get("evidence", [])),
    )


def _coverage_block(rows: tuple[CoverageView, ...] | list[CoverageView]) -> str:
    return "\n".join(f"- {row.verdict}: {row.requirement}" for row in rows)


def _summary(resume: TailoredResume, *, latest_version: int | None) -> ResumeSummaryView:
    return ResumeSummaryView(
        id=resume.id,
        target=_ref_of(resume),
        label=resume.target_label,
        status=str(resume.status),
        error_code=resume.error_code,
        error_message=resume.error_message,
        latest_version=latest_version,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


def _version_view(version: ResumeVersion) -> VersionView:
    return VersionView(
        id=version.id,
        number=version.number,
        label=version.label,
        source=version.source,
        model_id=version.model_id,
        created_at=version.created_at,
    )


def _revision_view(revision: Revision) -> RevisionView:
    return RevisionView(
        id=revision.id,
        request=revision.request,
        reply=revision.reply,
        has_proposal=revision.proposal is not None,
        applied_version_id=revision.applied_version_id,
        created_at=revision.created_at,
    )


def _template_view(
    id: str, *, name: str, note: str, is_built_in: bool, spec: TemplateSpec
) -> TemplateView:
    return TemplateView(
        id=id,
        name=name,
        note=note,
        is_built_in=is_built_in,
        spec=spec,
        page_width_mm=PAGE_WIDTH_MM,
        page_height_mm=PAGE_HEIGHT_MM,
        margin_top_mm=PAGE_MARGIN_TOP_MM,
        margin_side_mm=PAGE_MARGIN_SIDE_MM,
        trimmed_bullets=TRIMMED_BULLETS,
        trimmed_skills=TRIMMED_SKILLS,
    )


def _built_in_view(template: BuiltInTemplate) -> TemplateView:
    return _template_view(
        str(template.template),
        name=template.name,
        note=template.note,
        is_built_in=True,
        spec=template.spec,
    )


def _own_view(template: CustomTemplate) -> TemplateView:
    return _template_view(
        str(template.id), name=template.name, note="", is_built_in=False, spec=template.spec
    )


def _reading_view(reading: TemplateReading) -> TemplateReadingView:
    return TemplateReadingView(
        id=reading.id,
        status=str(reading.status),
        error_code=reading.error_code,
        error_message=reading.error_message,
        spec=TemplateSpec.from_dict(reading.spec) if reading.spec is not None else None,
        read=reading.read,
        defaulted=reading.defaulted,
        created_at=reading.created_at,
    )


def _template_id(resume: TailoredResume) -> str:
    if resume.custom_template_id is not None:
        return str(resume.custom_template_id)
    return str(resume.template or Template.ORGANIC)


async def _resolve_template(
    mine: OwnerResumes, template_id: str
) -> tuple[Template | None, uuid.UUID | None]:
    """A template id as the résumé stores it: a built-in template, or one of
    the user's own, which must be theirs."""
    try:
        return Template(template_id), None
    except ValueError:
        pass
    try:
        own_id = uuid.UUID(template_id)
    except ValueError as exc:
        raise ValidationError("no such template", template=template_id) from exc
    return None, (await _owned_template(mine, own_id)).id


async def _owned_template(mine: OwnerResumes, template_id: uuid.UUID) -> CustomTemplate:
    template = await mine.templates.get(template_id)
    if template is None:
        raise NotFoundError("template not found", template_id=str(template_id))
    return template


async def _spec_of(mine: OwnerResumes, resume: TailoredResume) -> TemplateSpec:
    if resume.custom_template_id is not None:
        return (await _owned_template(mine, resume.custom_template_id)).spec
    return BUILT_IN_TEMPLATES[resume.template or Template.ORGANIC].spec


def _export_view(export: Export, *, download_url: str | None) -> ExportView:
    return ExportView(
        id=export.id,
        version_id=export.version_id,
        template=export.template,
        status=str(export.status),
        error_code=export.error_code,
        error_message=export.error_message,
        download_url=download_url,
    )
