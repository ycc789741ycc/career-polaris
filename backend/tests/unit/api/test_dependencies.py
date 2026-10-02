"""Who is calling: the access token, read through the bearer scheme."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import current_user
from kernel.errors import UnauthenticatedError


class _Verifier:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self.tokens: list[str] = []

    def verify(self, token: str) -> SimpleNamespace:
        self.tokens.append(token)
        return SimpleNamespace(subject=self.subject)


def _deps(verifier: _Verifier) -> Any:
    return cast(Any, SimpleNamespace(verifier=verifier))


async def test_a_missing_token_is_unauthenticated() -> None:
    with pytest.raises(UnauthenticatedError):
        await current_user(None, _deps(_Verifier(str(uuid.uuid4()))))


async def test_the_token_is_verified_and_its_subject_is_the_account() -> None:
    account_id = uuid.uuid4()
    verifier = _Verifier(str(account_id))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="the-token")

    assert await current_user(credentials, _deps(verifier)) == account_id
    assert verifier.tokens == ["the-token"]


async def test_a_subject_that_is_not_an_account_id_is_unauthenticated() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="the-token")
    with pytest.raises(UnauthenticatedError):
        await current_user(credentials, _deps(_Verifier("not-a-uuid")))
