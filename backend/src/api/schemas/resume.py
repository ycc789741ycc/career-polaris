"""Resume Advisor's wire shapes: tailored résumés, versions, revisions, exports."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import Field

from advisor.resume import (
    ExportView,
    ResumeSummaryView,
    ResumeView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    SectionKind,
    SectionSlot,
    TemplateLimitsView,
    TemplateReadingView,
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
# A built-in template's name, or the id of one of the user's own (ADR 0040).
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
TemplateId = Annotated[str, Field(pattern=rf"^(organic|plain|{_UUID})$")]
LayoutName = Literal["single_column", "sidebar_left", "sidebar_right", "header_band"]
FontName = Literal["Caprasimo", "Figtree", "DejaVu Serif", "DejaVu Sans Mono"]
RuleName = Literal["none", "thin", "thick"]
HeadingCaseName = Literal["upper", "as_written"]
BulletName = Literal["dot", "dash", "none"]
# What moved on since the résumé was last written (ADR 0035).
OutdatedReasonName = Literal["evidence", "target"]


class OptionsBody(RequestModel):
    metrics: bool = True
    reorder: bool = True
    trim: bool = False


class ResumeRequest(TargetFields):
    template: TemplateId = "organic"
    options: OptionsBody = Field(default_factory=OptionsBody)


class SettingsRequest(RequestModel):
    template: TemplateId
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


class SectionRequest(RequestModel):
    """A section to fill from the sources: an empty one the résumé holds,
    shown once filled, or a new one of the user's own (ADR 0039, ADR 0043)."""

    kind: SectionKind
    # A section of the user's own needs its heading; no other kind takes one.
    title: str | None = Field(default=None, min_length=1, max_length=60)

    def slot(self) -> SectionSlot:
        return SectionSlot(self.kind, self.title if self.kind is SectionKind.CUSTOM else None)


class ResumeBullet(ApiModel):
    text: str
    evidence_ids: list[str]
    # "written" by the model (always cited) or "yours" (typed by the user).
    origin: Literal["written", "yours"]
    # The Target requirement this line answers, if any.
    answers: str | None


class ResumeEntry(ApiModel):
    """A position, project, school or talk."""

    title: str
    org: str
    when: str
    # Shown as text; never a live link.
    link: str
    bullets: list[ResumeBullet]


SectionKindName = Literal[
    "summary",
    "experience",
    "side_projects",
    "open_source",
    "education",
    "talks_and_writing",
    "skills",
    "certifications",
    "custom",
]


class ResumeSection(ApiModel):
    """One section. Its kind's shape decides which field it uses: ``text`` for
    the summary, ``entries`` for experience and the other entry kinds,
    ``items`` for skills and certifications, ``bullets`` for a custom one."""

    kind: SectionKindName
    # A custom section's heading; null for every other kind.
    title: str | None
    text: str
    entries: list[ResumeEntry]
    items: list[str]
    bullets: list[ResumeBullet]
    # A hidden section is kept and written like the rest, and never printed
    # (ADR 0043). Experience is always shown.
    is_shown: bool


class ResumeSectionSlot(ApiModel):
    kind: SectionKindName
    title: str | None
    is_shown: bool


class ResumeContent(ApiModel):
    name: str
    headline: str
    contact: str
    # Every section, in order, shown or hidden (ADR 0039, ADR 0043).
    sections: list[ResumeSection]

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
    # ready -> filling -> ready: one section being filled from the sources; a
    # failure to fill it leaves it ready, with the error (ADR 0039).
    status: Literal["drafting", "ready", "failed", "filling"]
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
    # What the user answered about this requirement in Fill the gap: what a
    # gap may be claimed from (ADR 0044). The verdict does not change.
    answers: list[EvidenceCitation]


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
    # A built-in template's name, or the id of one of the user's own.
    template: str
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
    # The sections every new version is written to, in order (ADR 0039).
    section_plan: list[ResumeSectionSlot]

    @classmethod
    def from_resume(cls, resume: ResumeView) -> TailoredResume:
        snapshot = resume.snapshot
        return cls(
            **ResumeSummary.from_view(resume.summary).model_dump(),
            template=resume.template,
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
                    answers=[
                        EvidenceCitation(id=a.id, reference=a.reference, fact=a.fact)
                        for a in c.answers
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
            section_plan=[
                ResumeSectionSlot(kind=str(slot.kind), title=slot.title, is_shown=slot.is_shown)
                for slot in resume.section_plan
            ],
        )


class ResumeExport(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    # The built-in template it was rendered in; null for one of the user's own.
    template: TemplateName | None
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
            template=str(export.template) if export.template else None,
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


class TemplateDesign(RequestModel):
    """A template's look as checked values, never markup (ADR 0040). Sizes in
    points. The server checks every value again, contrast included."""

    layout: LayoutName = "single_column"
    heading_font: FontName = "Caprasimo"
    body_font: FontName = "Figtree"
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    name_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    text_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    rule_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    rule: RuleName = "thick"
    name_pt: float
    heading_pt: float
    body_pt: float
    # For a sidebar layout: which list sections sit in the sidebar.
    sidebar_kinds: list[SectionKindName] = Field(default_factory=list, max_length=12)
    heading_case: HeadingCaseName = "upper"
    bullet: BulletName = "dot"


class TemplateRequest(RequestModel):
    name: str = Field(min_length=1, max_length=60)
    spec: TemplateDesign


class TemplateSpecBody(ApiModel):
    layout: LayoutName
    heading_font: FontName
    body_font: FontName
    accent_color: str
    name_color: str
    text_color: str
    rule_color: str
    rule: RuleName
    name_pt: float
    heading_pt: float
    body_pt: float
    sidebar_kinds: list[SectionKindName]
    heading_case: HeadingCaseName
    bullet: BulletName


class ResumeTemplate(ApiModel):
    """One template as the PDF renderer draws it, for the picker and the
    preview to draw the same page (ADR 0038, ADR 0040). Sizes in points, the
    page in millimetres."""

    # A built-in template's name, or the id of one of the user's own.
    id: str
    name: str
    note: str
    is_built_in: bool
    spec: TemplateSpecBody
    # The line under the header, as a CSS border shorthand.
    rule: str
    # The header band's tint, for the header_band layout.
    band_color: str
    # Worked out from the body size, as the renderer does.
    title_pt: float
    contact_pt: float
    small_pt: float
    page_width_mm: int
    page_height_mm: int
    margin_top_mm: int
    margin_side_mm: int
    # What "Trim to one page" keeps: bullets per position, and skills.
    trimmed_bullets: int
    trimmed_skills: int

    @classmethod
    def from_view(cls, template: TemplateView) -> ResumeTemplate:
        spec = template.spec
        title_pt, contact_pt, small_pt = spec.get_derived_pt()
        return cls(
            id=template.id,
            name=template.name,
            note=template.note,
            is_built_in=template.is_built_in,
            spec=TemplateSpecBody.model_validate(spec.to_dict()),
            rule=spec.get_rule_css(),
            band_color=spec.get_band_color(),
            title_pt=title_pt,
            contact_pt=contact_pt,
            small_pt=small_pt,
            page_width_mm=template.page_width_mm,
            page_height_mm=template.page_height_mm,
            margin_top_mm=template.margin_top_mm,
            margin_side_mm=template.margin_side_mm,
            trimmed_bullets=template.trimmed_bullets,
            trimmed_skills=template.trimmed_skills,
        )


class ResumeTemplateLimits(ApiModel):
    """What a template of the user's own may set, for the editor."""

    fonts: list[FontName]
    name_pt_range: tuple[float, float]
    heading_pt_range: tuple[float, float]
    body_pt_range: tuple[float, float]
    # The name and the text against the white page.
    min_contrast: float
    max_name: int
    # How many templates of their own a user may keep.
    max_templates: int
    # The largest PDF a template may start from (ADR 0041).
    upload_max_bytes: int

    @classmethod
    def from_view(cls, limits: TemplateLimitsView) -> ResumeTemplateLimits:
        # The fonts are checked against ``FontName`` here, not cast.
        return cls.model_validate(
            {
                "fonts": list(limits.fonts),
                "name_pt_range": limits.name_pt_range,
                "heading_pt_range": limits.heading_pt_range,
                "body_pt_range": limits.body_pt_range,
                "min_contrast": limits.min_contrast,
                "max_name": limits.max_name,
                "max_templates": limits.max_templates,
                "upload_max_bytes": limits.upload_max_bytes,
            }
        )


TemplateField = Literal[
    "layout",
    "heading_font",
    "body_font",
    "accent_color",
    "name_color",
    "text_color",
    "rule_color",
    "rule",
    "name_pt",
    "heading_pt",
    "body_pt",
    "sidebar_kinds",
    "heading_case",
    "bullet",
]


class TemplateReading(ApiModel):
    """A PDF being read for its style (ADR 0041). Once ready, a draft spec the
    editor opens on, with which values were read from the file and which took
    Organic's. Nothing of the file's text is kept."""

    id: uuid.UUID
    # reading -> ready | failed
    status: Literal["reading", "ready", "failed"]
    error: JobError | None
    spec: TemplateSpecBody | None
    read: list[TemplateField]
    defaulted: list[TemplateField]
    created_at: Timestamp

    @classmethod
    def from_view(cls, reading: TemplateReadingView) -> TemplateReading:
        return cls.model_validate(
            {
                "id": reading.id,
                "status": reading.status,
                "error": JobError.of(reading.error_code, reading.error_message),
                "spec": reading.spec.to_dict() if reading.spec else None,
                "read": list(reading.read),
                "defaulted": list(reading.defaulted),
                "created_at": reading.created_at,
            }
        )


class ResumeTemplatePage(Page[ResumeTemplate]):
    pass
