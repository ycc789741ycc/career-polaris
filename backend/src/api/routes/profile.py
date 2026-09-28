"""Profile HTTP surface: connectors, resume upload and the evidence list.

Nothing here parses an uploaded file. The request handler stores the bytes and
queues a worker job; parsing hostile documents in the API process is exactly
what section 4 forbids.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile

from advisor.profile import (
    GITHUB_SCOPE_DESCRIPTIONS,
    JIRA_SCOPE_DESCRIPTIONS,
    authorize_url,
    exchange_code,
    sign_state,
    verify_state,
)
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.common import Accepted
from api.schemas.profile import (
    AuthorizationUrl,
    CallbackRequest,
    Connection,
    ConnectionPage,
    ConnectionResult,
    DownloadUrl,
    Evidence,
    EvidencePage,
    Profile,
    ResumeFile,
    ResumeFilePage,
    ResumeUpload,
)
from kernel.config import Settings, must
from kernel.fetch import GuardedClient
from kernel.paging import paginate
from wiring.queue import enqueue

router = APIRouter(tags=["profile"])


def _redirect_uri(settings: Settings, kind: str) -> str:
    """Where the provider sends the browser back to: a page in the SPA.

    It has to be the SPA, not this API. The provider redirects with a GET
    carrying `code` and `state`, but exchanging them needs the user's access
    token, which lives only in the SPA's memory. So the SPA receives the
    redirect and POSTs both to `/connections/{kind}/callback` here.

    Built explicitly, because an f-string over an unset value would quietly
    produce "None/connections/..." and fail at the provider instead of here.
    """
    base = must(settings.oauth_redirect_base_url, "OAUTH_REDIRECT_BASE_URL")
    return f"{base}/connections/{kind}/callback"


SCOPE_COPY = {
    "github": GITHUB_SCOPE_DESCRIPTIONS,
    "jira": JIRA_SCOPE_DESCRIPTIONS,
}


@router.get("/connections")
async def list_connections(user: CurrentUser, deps: Deps, paging: Paging) -> ConnectionPage:
    """Every connector, connected or not."""
    connected = {c.kind: c for c in await deps.profile.connections(user)}
    rows = [
        Connection.from_view(kind, connected.get(kind), scopes)
        for kind, scopes in SCOPE_COPY.items()
    ]
    return ConnectionPage.of(paginate(rows, paging.page, paging.page_size), lambda row: row)


@router.get("/connections/{kind}/authorize-url")
async def start_authorization(kind: str, user: CurrentUser, deps: Deps) -> AuthorizationUrl:
    settings = deps.settings
    secret = settings.require_master_key().get_secret_value()
    client_id = (
        must(settings.github_oauth_client_id, "GITHUB_OAUTH_CLIENT_ID")
        if kind == "github"
        else must(settings.jira_oauth_client_id, "JIRA_OAUTH_CLIENT_ID")
    )
    return AuthorizationUrl(
        url=authorize_url(
            kind,
            jira_oauth_base=must(settings.jira_oauth_base_url, "JIRA_OAUTH_BASE_URL"),
            client_id=client_id,
            redirect_uri=_redirect_uri(settings, kind),
            state=sign_state(user, kind, secret=secret),
        )
    )


@router.post("/connections/{kind}/callback", status_code=201)
async def complete_authorization(
    kind: str, body: CallbackRequest, user: CurrentUser, deps: Deps
) -> ConnectionResult:
    settings = deps.settings
    secret = settings.require_master_key().get_secret_value()
    owner_id, state_kind = verify_state(body.state, secret=secret)
    if owner_id != user or state_kind != kind:
        from kernel.errors import ForbiddenError

        raise ForbiddenError("this authorization was started by someone else")

    client_id, client_secret = (
        (
            must(settings.github_oauth_client_id, "GITHUB_OAUTH_CLIENT_ID"),
            must(settings.github_oauth_client_secret, "GITHUB_OAUTH_CLIENT_SECRET"),
        )
        if kind == "github"
        else (
            must(settings.jira_oauth_client_id, "JIRA_OAUTH_CLIENT_ID"),
            must(settings.jira_oauth_client_secret, "JIRA_OAUTH_CLIENT_SECRET"),
        )
    )

    async with GuardedClient(
        timeout_seconds=settings.crawl_http_timeout_seconds, user_agent=settings.service_name
    ) as client:
        token = await exchange_code(
            client,
            kind,
            jira_oauth_base=must(settings.jira_oauth_base_url, "JIRA_OAUTH_BASE_URL"),
            code=body.code,
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
            redirect_uri=_redirect_uri(settings, kind),
        )

    connection = await deps.profile.store_connection(
        user,
        kind=kind,
        access_token=str(token["access_token"]),
        refresh_token=token.get("refresh_token"),
        scopes=tuple(str(token.get("scope", "")).split()),
        expires_at=None,
    )
    await enqueue("profile.sync_connection", owner_id=str(user), kind=kind)
    return ConnectionResult.from_view(connection)


@router.post("/connections/{kind}/sync", status_code=202)
async def sync_now(kind: str, user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("profile.sync_connection", owner_id=str(user), kind=kind)
    return Accepted()


@router.delete("/connections/{kind}", status_code=204)
async def disconnect(kind: str, user: CurrentUser, deps: Deps) -> None:
    await deps.profile.disconnect(user, kind)


@router.post("/resumes", status_code=202)
async def upload_resume(
    user: CurrentUser, deps: Deps, file: UploadFile = File(...)
) -> ResumeUpload:
    content = await file.read()
    resume = await deps.profile.upload_resume(
        user,
        filename=file.filename or "resume",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    await enqueue("profile.parse_resume", owner_id=str(user), resume_id=str(resume.id))
    return ResumeUpload.from_view(resume)


@router.get("/resumes")
async def list_resumes(user: CurrentUser, deps: Deps, paging: Paging) -> ResumeFilePage:
    """Uploaded résumés, newest first."""
    found = await deps.profile.resumes(user, page=paging.page, page_size=paging.page_size)
    return ResumeFilePage.of(found, ResumeFile.from_view)


@router.get("/resumes/{resume_id}/download-url")
async def resume_url(resume_id: uuid.UUID, user: CurrentUser, deps: Deps) -> DownloadUrl:
    """Uploads are never publicly addressable; this is short-lived."""
    return DownloadUrl(url=await deps.profile.resume_download_url(user, resume_id))


@router.get("/evidence")
async def list_evidence(user: CurrentUser, deps: Deps, paging: Paging) -> EvidencePage:
    """Every fact on the profile, newest first. The list that grows with each sync."""
    found = await deps.profile.evidence(user, page=paging.page, page_size=paging.page_size)
    return EvidencePage.of(found, Evidence.from_view)


@router.get("/profile")
async def read_profile(user: CurrentUser, deps: Deps) -> Profile:
    return Profile.from_view(await deps.profile.snapshot(user))


__all__ = ["router"]
