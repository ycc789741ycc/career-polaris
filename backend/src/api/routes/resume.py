"""Resume Advisor HTTP surface.

Routes live under ``/tailored-resumes``: ``/resumes`` is the profile's, for
uploaded résumé files. The revision chat is the one streamed route — Server-Sent
Events over a POST, since it carries the current draft and a bearer token that
``EventSource`` cannot send.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from advisor.resume import Options, SectionKind
from api.dependencies import CurrentUser, Deps, Paging, TargetQuery
from api.schemas.common import TargetEstimate
from api.schemas.resume import (
    ExportRequest,
    ResumeExport,
    ResumeRequest,
    ResumeSummary,
    ResumeSummaryPage,
    ResumeTemplate,
    ResumeTemplatePage,
    ResumeVersion,
    RevisionRequest,
    SectionRequest,
    SettingsRequest,
    TailoredResume,
    VersionRequest,
    revision_event,
)
from wiring.queue import enqueue

router = APIRouter(tags=["resume"])


@router.get("/tailored-resumes/cost-estimate")
async def cost_estimate(target: TargetQuery, user: CurrentUser, deps: Deps) -> TargetEstimate:
    """Writing runs on the user's key, so it is priced first."""
    return TargetEstimate.model_validate(await deps.resume.estimate_cost(user, target))


@router.post("/tailored-resumes", status_code=202)
async def write_resume(body: ResumeRequest, user: CurrentUser, deps: Deps) -> ResumeSummary:
    """Records the résumé as drafting and queues it; poll ``GET /tailored-resumes/{id}``."""
    resume = await deps.resume.request(
        user,
        body.ref(),
        template=body.template,
        options=Options(**body.options.model_dump()),
    )
    await enqueue("resume.generate", owner_id=str(user), resume_id=str(resume.id))
    return ResumeSummary.from_view(resume)


@router.post("/tailored-resumes/{resume_id}/regenerate", status_code=202)
async def regenerate_resume(resume_id: uuid.UUID, user: CurrentUser, deps: Deps) -> ResumeSummary:
    """Writes the résumé again as its next version, priced first by
    ``/tailored-resumes/cost-estimate``; poll ``GET /tailored-resumes/{id}``
    (ADR 0035)."""
    resume = await deps.resume.redraft(user, resume_id)
    await enqueue("resume.generate", owner_id=str(user), resume_id=str(resume.id))
    return ResumeSummary.from_view(resume)


@router.get("/tailored-resumes/{resume_id}/sections/estimate")
async def section_estimate(
    resume_id: uuid.UUID,
    user: CurrentUser,
    deps: Deps,
    kind: Annotated[SectionKind, Query()],
    title: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
) -> TargetEstimate:
    """Filling a section from the sources runs on the user's key, so it is
    priced first (ADR 0039)."""
    slot = SectionRequest(kind=kind, title=title).slot()
    return TargetEstimate.model_validate(await deps.resume.estimate_section(user, resume_id, slot))


@router.post("/tailored-resumes/{resume_id}/sections", status_code=202)
async def add_section(
    resume_id: uuid.UUID, body: SectionRequest, user: CurrentUser, deps: Deps
) -> ResumeSummary:
    """Adds the section and fills it from the sources; poll
    ``GET /tailored-resumes/{id}`` while it is ``filling`` (ADR 0039)."""
    slot = body.slot()
    resume = await deps.resume.request_section(user, resume_id, slot)
    await enqueue(
        "resume.fill_section",
        owner_id=str(user),
        resume_id=str(resume.id),
        kind=str(slot.kind),
        title=slot.title,
    )
    return ResumeSummary.from_view(resume)


@router.get("/tailored-resumes")
async def saved(user: CurrentUser, deps: Deps, paging: Paging) -> ResumeSummaryPage:
    """Saved résumés, most recently changed first."""
    found = await deps.resume.saved(user, page=paging.page, page_size=paging.page_size)
    return ResumeSummaryPage.of(found, ResumeSummary.from_view)


@router.get("/tailored-resumes/{resume_id}")
async def get_resume(
    resume_id: uuid.UUID,
    user: CurrentUser,
    deps: Deps,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> TailoredResume:
    return TailoredResume.from_resume(await deps.resume.get(user, resume_id, number=version))


@router.put("/tailored-resumes/{resume_id}/settings", status_code=204)
async def update_settings(
    resume_id: uuid.UUID, body: SettingsRequest, user: CurrentUser, deps: Deps
) -> None:
    await deps.resume.update_settings(
        user,
        resume_id,
        template=body.template,
        options=Options(**body.options.model_dump()),
    )


@router.post("/tailored-resumes/{resume_id}/versions", status_code=201)
async def save_version(
    resume_id: uuid.UUID, body: VersionRequest, user: CurrentUser, deps: Deps
) -> ResumeVersion:
    version = await deps.resume.save_version(
        user, resume_id, content=body.content, label=body.label
    )
    return ResumeVersion.from_view(version)


@router.post("/tailored-resumes/{resume_id}/revisions")
async def revise(
    resume_id: uuid.UUID, body: RevisionRequest, user: CurrentUser, deps: Deps
) -> EventSourceResponse:
    """The revision chat. Events: ``text`` as prose arrives, then exactly one of
    ``proposal`` (applied only on request) or ``error`` ({code, message})."""

    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in deps.resume.revise(
            user, resume_id, request=body.message, content=body.content
        ):
            yield revision_event(event)

    return EventSourceResponse(events())


@router.post("/tailored-resumes/{resume_id}/revisions/{revision_id}/apply", status_code=201)
async def apply_revision(
    resume_id: uuid.UUID, revision_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> ResumeVersion:
    """An accepted chat edit becomes a new version."""
    return ResumeVersion.from_view(await deps.resume.apply_revision(user, resume_id, revision_id))


@router.get("/resume-templates")
async def templates(user: CurrentUser, deps: Deps, paging: Paging) -> ResumeTemplatePage:
    """Every template as the PDF renderer draws it, for the preview (ADR 0038)."""
    found = deps.resume.templates(page=paging.page, page_size=paging.page_size)
    return ResumeTemplatePage.of(found, ResumeTemplate.from_view)


@router.post("/tailored-resumes/{resume_id}/exports", status_code=202)
async def request_export(
    resume_id: uuid.UUID, body: ExportRequest, user: CurrentUser, deps: Deps
) -> ResumeExport:
    """Renders on the worker's ``docs`` queue; poll ``GET /resume-exports/{id}``,
    whose link downloads the file once it is ready. An unchanged export is
    reused and nothing is queued (ADR 0038)."""
    export = await deps.resume.request_export(user, resume_id, number=body.version)
    if export.status == "rendering":
        await enqueue("resume.export", owner_id=str(user), export_id=str(export.id))
    return ResumeExport.from_view(export)


@router.get("/resume-exports/{export_id}")
async def get_export(export_id: uuid.UUID, user: CurrentUser, deps: Deps) -> ResumeExport:
    return ResumeExport.from_view(await deps.resume.get_export(user, export_id))
