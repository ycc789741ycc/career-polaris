"""Request-scoped dependencies: who is calling, and what they may use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request

from kernel.errors import UnauthenticatedError
from kernel.logging import trace_id_var
from kernel.paging import check_page
from wiring.container import Container, container

REFRESH_COOKIE = "jsa_refresh"

# The most one page may hold. Without a page_size a list comes back whole (ADR 0014).
MAX_PAGE_SIZE = 100


def get_container() -> Container:
    return container()


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    deps: Container = Depends(get_container),
) -> uuid.UUID:
    """Verify the access token and return the account it belongs to.

    We issue these tokens ourselves, so the subject *is* the account id and no
    database round trip is needed to resolve it. Signature, issuer, audience
    and expiry are still checked on every request.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthenticatedError("a bearer token is required")

    user = deps.verifier.verify(authorization.split(" ", 1)[1].strip())
    try:
        account_id = uuid.UUID(user.subject)
    except ValueError as exc:
        raise UnauthenticatedError("token subject is not an account id") from exc

    trace_id_var.set(str(account_id))
    return account_id


def refresh_token_from(request: Request) -> str | None:
    """The refresh token lives in an httpOnly cookie, never in the body.

    That is what keeps it out of reach of any cross-site scripting bug: the
    page can send it, but cannot read it.
    """
    return request.cookies.get(REFRESH_COOKIE)


CurrentUser = Annotated[uuid.UUID, Depends(current_user)]
Deps = Annotated[Container, Depends(get_container)]


@dataclass(frozen=True, slots=True)
class PageQuery:
    page: int
    page_size: int | None


def page_query(
    page: Annotated[int, Query(ge=1, description="1-based.")] = 1,
    page_size: Annotated[
        int | None,
        Query(ge=1, le=MAX_PAGE_SIZE, description="Omit it for the whole list, on page 1."),
    ] = None,
) -> PageQuery:
    """The same two paging parameters on every list endpoint (ADR 0014)."""
    # Page 2 of an unpaged list is a caller mistake: the usual 422 envelope.
    check_page(page, page_size)
    return PageQuery(page=page, page_size=page_size)


Paging = Annotated[PageQuery, Depends(page_query)]
