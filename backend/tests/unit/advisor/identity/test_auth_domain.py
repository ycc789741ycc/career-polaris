"""Lockout and refresh-token rules. Pure — nothing is hashed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from advisor.identity.domain import (
    LOCKOUT_WINDOW,
    MAX_FAILED_ATTEMPTS,
    LockoutState,
    RefreshRejectedError,
    RefreshTokenState,
    new_refresh_token,
    normalize_email,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("  Maya@Example.COM ", "maya@example.com"), ("a@b.c", "a@b.c")],
)
def test_email_is_normalised_so_there_is_one_account_per_address(typed: str, stored: str) -> None:
    assert normalize_email(typed) == stored


# -- lockout ----------------------------------------------------------------


def fresh() -> LockoutState:
    return LockoutState(failed_attempts=0, last_failed_at=None)


def test_a_new_account_is_not_locked() -> None:
    assert not fresh().is_locked(now=NOW)


def test_locking_happens_only_after_the_allowed_attempts() -> None:
    state = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        state = state.after_failure(now=NOW)
        assert not state.is_locked(now=NOW)
    state = state.after_failure(now=NOW)
    assert state.is_locked(now=NOW)


def test_a_lock_expires_rather_than_being_permanent() -> None:
    """A permanent lock lets an attacker lock someone out of their own account."""
    state = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS):
        state = state.after_failure(now=NOW)
    assert state.is_locked(now=NOW)
    assert not state.is_locked(now=NOW + LOCKOUT_WINDOW)


def test_the_caller_can_say_when_the_lock_lifts() -> None:
    state = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS):
        state = state.after_failure(now=NOW)
    assert state.unlocks_at(now=NOW) == NOW + LOCKOUT_WINDOW
    assert fresh().unlocks_at(now=NOW) is None


def test_failures_after_the_window_start_counting_again() -> None:
    state = fresh().after_failure(now=NOW).after_failure(now=NOW)
    later = state.after_failure(now=NOW + LOCKOUT_WINDOW + timedelta(seconds=1))
    assert later.failed_attempts == 1


def test_a_successful_sign_in_clears_the_count() -> None:
    state = fresh().after_failure(now=NOW).after_failure(now=NOW).after_success()
    assert state.failed_attempts == 0
    assert not state.is_locked(now=NOW)


# -- refresh tokens ---------------------------------------------------------


def usable() -> RefreshTokenState:
    return RefreshTokenState(expires_at=NOW + timedelta(days=30), revoked_at=None, used_at=None)


def test_a_fresh_refresh_token_is_usable() -> None:
    usable().assert_usable(now=NOW)


def test_a_revoked_token_is_refused() -> None:
    state = RefreshTokenState(expires_at=NOW + timedelta(days=30), revoked_at=NOW, used_at=None)
    with pytest.raises(RefreshRejectedError, match="signed out"):
        state.assert_usable(now=NOW)


def test_reusing_a_token_is_refused_because_rotation_makes_it_single_use() -> None:
    """Seeing one twice is either a replay or a theft, and we cannot tell which."""
    state = RefreshTokenState(expires_at=NOW + timedelta(days=30), revoked_at=None, used_at=NOW)
    with pytest.raises(RefreshRejectedError, match="already used"):
        state.assert_usable(now=NOW)


def test_an_expired_token_is_refused() -> None:
    state = RefreshTokenState(expires_at=NOW, revoked_at=None, used_at=None)
    with pytest.raises(RefreshRejectedError, match="expired"):
        state.assert_usable(now=NOW)


def test_refresh_tokens_are_unguessable_and_unique() -> None:
    tokens = {new_refresh_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(token) >= 40 for token in tokens)
