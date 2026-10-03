"""Resume Advisor's wire shapes: tailored résumés, versions, revisions, exports."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from advisor.resume import (
    ExportView,
    ResumeSummaryView,
    ResumeView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    Template,
    TemplateView,
    VersionView,
)
from api.schemas.common import (
    ApiModel,
    EvidenceCitation,
    JobError,
    Page,
    RequestModel,
    Timestamp,
)
from api.schemas.target import TargetFields, TargetRefBody

TemplateName = Literal["organic", "plain"]
# What moved on since the résumé was last written (ADR 0035).
OutdatedReasonName = Literal["evidence", "target"]


class OptionsBody(RequestModel):
    metrics: bool = True
    reorder: bool = True
    trim: bool = False


class ResumeRequest(TargetFields):
    template: Template = Template.ORGANIC
    options: OptionsBody = Field(default_factory=OptionsBody)


class SettingsRequest(RequestModel):
    template: Template
    options: OptionsBody


class VersionRequest(RequestModel):
    content: dict[str, Any]
    label: str | None = Field(default=None, max_length=200)


class RevisionRequest(RequestModel):
    message: str = Field(min_length=1, max_length=2000)
    # The draft as the user sees it now, saved or not.
    content: dict[str, Any]


class ExportRequest(RequestModel):
    version: int = Field(ge=1)


class ResumeBullet(ApiModel):
    text: str
    evidence_ids: list[str]
    # "written" by the model (always cited) or "yours" (typed by the user).
    origin: Literal["written", "yours"]
    # The Target requirement this line answers, if any.
    answers: str | None


class ResumePosition(ApiModel):
    title: str
    org: str
    when: str
    bullets: list[ResumeBullet]


class ResumeContent(ApiModel):
    name: str
    headline: str
    contact: str
    summary: str
    experience: list[ResumePosition]
    skills: list[str]

    @classmethod
    def from_dict(cls, content: dict[str, Any]) -> ResumeContent:
        # The domain owns the content's shape (``ResumeContent.to_dict``); this
        # checks that shape against the contract rather than restating it.
        return cls.model_validate(content)


class ResumeSummary(ApiModel):
    id: uuid.UUID
    target: TargetRefBody
    label: str
    # drafting -> ready | failed. A failure carries the error's stable code.
    status: Literal["drafting", "ready", "failed"]
    error: JobError | None
    latest_version: int | None
    created_at: Timestamp
    updated_at: Timestamp

    @classmethod
    def from_view(cls, resume: ResumeSummaryView) -> ResumeSummary:
        return cls(
            id=resume.id,
            target=TargetRefBody.from_ref(resume.target),
            label=resume.label,
            status=resume.status,
            error=JobError.of(resume.error_code, resume.error_message),
            latest_version=resume.latest_version,
            created_at=resume.created_at,
            updated_at=resume.updated_at,
        )


class ResumeVersion(ApiModel):
    id: uuid.UUID
    number: int
    label: str
    # "answers": rewritten after Fill the gap, before ADR 0035; nothing new
    # is saved with it.
    source: Literal["generated", "manual", "chat", "answers"]
    model_id: str | None
    created_at: Timestamp

    @classmethod
    def from_view(cls, version: VersionView) -> ResumeVersion:
        return cls(
            id=version.id,
            number=version.number,
            label=version.label,
            source=str(version.source),
            model_id=version.model_id,
            created_at=version.created_at,
        )


class ResumeOptions(ApiModel):
    metrics: bool
    reorder: bool
    trim: bool


class ResumeSnapshot(ApiModel):
    title: str
    company: str
    role_name: str | None
    fit: int | None
    basis: Literal["role", "opening", "posting"]


class Coverage(ApiModel):
    requirement: str
    verdict: Literal["covered", "partial", "gap"]
    evidence: list[EvidenceCitation]


class EvidenceNote(ApiModel):
    reference: str
    fact: str


class Revision(ApiModel):
    id: uuid.UUID
    request: str
    reply: str
    has_proposal: bool
    applied_version_id: uuid.UUID | None
    created_at: Timestamp


class TailoredResume(ResumeSummary):
    template: TemplateName
    options: ResumeOptions
    snapshot: ResumeSnapshot | None
    coverage: list[Coverage]
    version: ResumeVersion | None
    content: ResumeContent | None
    # Cited evidence, by handle, for the grey note under each line.
    evidence: dict[str, EvidenceNote]
    versions: list[ResumeVersion]
    revisions: list[Revision]
    # Whether the evidence or the Target has changed since the résumé was last
    # written. Regenerating is a request the user confirms (ADR 0035).
    is_outdated: bool
    outdated_by: list[OutdatedReasonName]

    @classmethod
    def from_resume(cls, resume: ResumeView) -> TailoredResume:
        snapshot = resume.snapshot
        return cls(
            **ResumeSummary.from_view(resume.summary).model_dump(),
            template=str(resume.template),
            options=ResumeOptions(
                metrics=resume.options.metrics,
                reorder=resume.options.reorder,
                trim=resume.options.trim,
            ),
            snapshot=(
                ResumeSnapshot(
                    title=snapshot.title,
                    company=snapshot.company,
                    role_name=snapshot.role_name,
                    fit=snapshot.fit_score,
                    basis=str(snapshot.basis),
                )
                if snapshot
                else None
            ),
            coverage=[
                Coverage(
                    requirement=c.requirement,
                    verdict=c.verdict,
                    evidence=[
                        EvidenceCitation(id=e.id, reference=e.reference, fact=e.fact)
                        for e in c.evidence
                    ],
                )
                for c in resume.coverage
            ],
            version=ResumeVersion.from_view(resume.version) if resume.version else None,
            content=ResumeContent.from_dict(resume.content.to_dict()) if resume.content else None,
            evidence={
                key: EvidenceNote(reference=note.reference, fact=note.fact)
                for key, note in resume.evidence.items()
            },
            versions=[ResumeVersion.from_view(v) for v in resume.versions],
            revisions=[
                Revision(
                    id=r.id,
                    request=r.request,
                    reply=r.reply,
                    has_proposal=r.has_proposal,
                    applied_version_id=r.applied_version_id,
                    created_at=r.created_at,
                )
                for r in resume.revisions
            ],
            is_outdated=resume.is_outdated,
            outdated_by=[str(r) for r in resume.outdated_by],
        )


class ResumeExport(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    template: TemplateName
    # rendering -> ready | failed
    status: Literal["rendering", "ready", "failed"]
    error: JobError | None
    # Short-lived and signed, and it downloads the file rather than opening it
    # (ADR 0038). The file itself is never public.
    download_url: str | None

    @classmethod
    def from_view(cls, export: ExportView) -> ResumeExport:
        return cls(
            id=export.id,
            version_id=export.version_id,
            template=str(export.template),
            status=export.status,
            error=JobError.of(export.error_code, export.error_message),
            download_url=export.download_url,
        )


# The revision chat's Server-Sent Events. They are not in the OpenAPI document,
# which cannot describe a stream, but building them here keeps their shape in
# one place with every other body.


class RevisionTextEvent(ApiModel):
    text: str


class RevisionProposalEvent(ApiModel):
    revision_id: uuid.UUID
    reply: str
    # Applied only when the user asks for it.
    proposal: ResumeContent | None


def revision_event(event: RevisionText | RevisionDone | RevisionFailed) -> dict[str, str]:
    """One chat event as ``sse_starlette`` sends it: a name and a JSON body."""
    if isinstance(event, RevisionText):
        return {"event": "text", "data": RevisionTextEvent(text=event.text).model_dump_json()}
    if isinstance(event, RevisionDone):
        body = RevisionProposalEvent(
            revision_id=event.revision_id,
            reply=event.reply,
            proposal=(
                ResumeContent.from_dict(event.proposal.to_dict()) if event.proposal else None
            ),
        )
        return {"event": "proposal", "data": body.model_dump_json()}
    detail = JobError(code=event.code, message=event.message)
    return {"event": "error", "data": detail.model_dump_json()}


class ResumeSummaryPage(Page[ResumeSummary]):
    pass


class ResumeTemplate(ApiModel):
    """One template as the PDF renderer draws it, for the picker and the
    preview to draw the same page (ADR 0038). Sizes in points, the page in
    millimetres."""

    id: TemplateName
    name: str
    note: str
    # The line under the header, as a CSS border shorthand.
    rule: str
    swatch: str
    name_color: str
    dot_color: str
    heading_font: str
    body_font: str
    page_width_mm: int
    page_height_mm: int
    margin_top_mm: int
    margin_side_mm: int
    name_pt: float
    title_pt: float
    body_pt: float
    contact_pt: float
    small_pt: float
    heading_pt: float
    # What "Trim to one page" keeps: bullets per position, and skills.
    trimmed_bullets: int
    trimmed_skills: int

    @classmethod
    def from_view(cls, template: TemplateView) -> ResumeTemplate:
        look = template.look
        return cls(
            id=str(look.template),
            name=look.name,
            note=look.note,
            rule=look.rule,
            swatch=look.swatch,
            name_color=look.name_color,
            dot_color=look.dot_color,
            heading_font=look.heading_font,
            body_font=look.body_font,
            page_width_mm=template.page_width_mm,
            page_height_mm=template.page_height_mm,
            margin_top_mm=template.margin_top_mm,
            margin_side_mm=template.margin_side_mm,
            name_pt=template.name_pt,
            title_pt=template.title_pt,
            body_pt=template.body_pt,
            contact_pt=template.contact_pt,
            small_pt=template.small_pt,
            heading_pt=template.heading_pt,
            trimmed_bullets=template.trimmed_bullets,
            trimmed_skills=template.trimmed_skills,
        )


class ResumeTemplatePage(Page[ResumeTemplate]):
    pass
