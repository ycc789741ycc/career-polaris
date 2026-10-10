"""Identity use cases against in-memory storage: sign-in, sessions, the AI
credential and the budget, decided with no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from advisor.identity import AiSource, AuthService, IdentityService, Provider
from advisor.identity.domain import (
    MAX_FAILED_ATTEMPTS,
    CredentialStatus,
    FederatedIdentity,
    IdTokenClaims,
    ProviderCredentialFailed,
    UsageBudgetExceeded,
    digest,
)
from kernel.ai_gateway.ports import Funding, PlatformCredential, UsageRecord
from kernel.crypto import decrypt
from kernel.errors import (
    BudgetExceededError,
    ConflictError,
    CredentialMissingError,
    PlatformAiNotEligibleError,
    PlatformAiUnavailableError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)
from tests.unit.advisor.identity.fakes import FakeIdentityUnitOfWork

PASSWORD = "a perfectly fine passphrase"

pytestmark = pytest.mark.usefixtures("clean_env")


def _auth(uow: FakeIdentityUnitOfWork) -> AuthService:
    return AuthService(
        uow,
        secret="s" * 48,
        issuer="careerpolaris-test",
        audience="careerpolaris-test-api",
        access_ttl_seconds=900,
        refresh_ttl_days=30,
        default_monthly_cap_usd=Decimal("20"),
    )


def _identity(uow: FakeIdentityUnitOfWork) -> IdentityService:
    return IdentityService(uow, default_monthly_cap_usd=Decimal("20"))


# --- registration and sign-in ----------------------------------------------


async def test_registering_opens_a_session_and_sets_the_default_budget() -> None:
    uow = FakeIdentityUnitOfWork()
    session = await _auth(uow).register(email=" Ada@Example.COM ", password=PASSWORD)

    assert session.email == "ada@example.com"
    (account,) = uow.store.accounts.values()
    (budget,) = uow.store.budgets.values()
    assert budget.owner_id == account.id and budget.monthly_cap_usd == Decimal("20")
    (token,) = uow.store.refresh_tokens.values()
    assert token.token_hash == digest(session.refresh_token)


async def test_an_address_registers_once() -> None:
    auth = _auth(FakeIdentityUnitOfWork())
    await auth.register(email="ada@example.com", password=PASSWORD)
    with pytest.raises(ConflictError):
        await auth.register(email="ADA@example.com", password=PASSWORD)


async def test_a_weak_password_is_refused() -> None:
    with pytest.raises(ValidationError):
        await _auth(FakeIdentityUnitOfWork()).register(email="ada@example.com", password="short")


async def test_wrong_passwords_lock_the_account_and_the_lock_is_recorded() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    await auth.register(email="ada@example.com", password=PASSWORD)

    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(UnauthenticatedError):
            await auth.sign_in(email="ada@example.com", password="not the passphrase")
    with pytest.raises(RateLimitedError):
        await auth.sign_in(email="ada@example.com", password=PASSWORD)

    (credential,) = uow.store.passwords.values()
    assert credential.failed_attempts == MAX_FAILED_ATTEMPTS


async def test_a_good_sign_in_clears_earlier_failures() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    await auth.register(email="ada@example.com", password=PASSWORD)
    with pytest.raises(UnauthenticatedError):
        await auth.sign_in(email="ada@example.com", password="wrong wrong wrong")

    await auth.sign_in(email="ada@example.com", password=PASSWORD)

    (credential,) = uow.store.passwords.values()
    assert credential.failed_attempts == 0 and credential.last_failed_at is None


async def test_an_unknown_address_fails_like_a_wrong_password() -> None:
    with pytest.raises(UnauthenticatedError, match="do not match"):
        await _auth(FakeIdentityUnitOfWork()).sign_in(email="nobody@example.com", password=PASSWORD)


# --- refresh and sign-out --------------------------------------------------


async def test_a_refresh_rotates_and_a_reused_token_revokes_the_whole_family() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    first = await auth.register(email="ada@example.com", password=PASSWORD)

    second = await auth.refresh(refresh_token=first.refresh_token)
    assert second.refresh_token != first.refresh_token

    with pytest.raises(UnauthenticatedError):
        await auth.refresh(refresh_token=first.refresh_token)
    # The theft response is committed, not rolled back by the rejection.
    assert all(t.revoked_at is not None for t in uow.store.refresh_tokens.values())
    with pytest.raises(UnauthenticatedError):
        await auth.refresh(refresh_token=second.refresh_token)


async def test_signing_out_ends_the_chain_and_is_idempotent() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    session = await auth.register(email="ada@example.com", password=PASSWORD)

    await auth.sign_out(refresh_token=session.refresh_token)
    await auth.sign_out(refresh_token=session.refresh_token)
    await auth.sign_out(refresh_token=None)

    with pytest.raises(UnauthenticatedError):
        await auth.refresh(refresh_token=session.refresh_token)


async def test_signing_out_everywhere_revokes_only_that_accounts_sessions() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    ada = await auth.register(email="ada@example.com", password=PASSWORD)
    await auth.sign_in(email="ada@example.com", password=PASSWORD)
    bob = await auth.register(email="bob@example.com", password=PASSWORD)

    assert await auth.sign_out_everywhere(ada.account_id) == 2
    await auth.refresh(refresh_token=bob.refresh_token)


# --- Google ----------------------------------------------------------------


def _claims(email: str, subject: str = "google-sub-1") -> IdTokenClaims:
    return IdTokenClaims(subject=subject, email=email, email_verified=True, nonce="n")


async def test_a_verified_google_address_takes_over_a_password_account() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)
    squatter = await auth.register(email="ada@example.com", password=PASSWORD)

    session = await auth.sign_in_with_google(_claims("ada@example.com"))

    assert session.account_id == squatter.account_id
    assert uow.store.passwords == {}
    with pytest.raises(UnauthenticatedError):
        await auth.refresh(refresh_token=squatter.refresh_token)
    (link,) = uow.store.federated.values()
    assert link.account_id == squatter.account_id and link.subject == "google-sub-1"


async def test_a_new_google_user_gets_an_account_and_a_budget_and_signs_in_again() -> None:
    uow = FakeIdentityUnitOfWork()
    auth = _auth(uow)

    first = await auth.sign_in_with_google(_claims("new@example.com"))
    again = await auth.sign_in_with_google(_claims("new@example.com"))

    assert again.account_id == first.account_id
    assert len(uow.store.accounts) == 1 and len(uow.store.federated) == 1
    assert len(uow.store.budgets) == 1


# --- the AI credential and budget ------------------------------------------


async def test_the_credential_is_write_only_and_encrypted() -> None:
    uow = FakeIdentityUnitOfWork()
    owner = uuid.uuid4()
    identity = _identity(uow)

    view = await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-secret-1234", base_url=None
    )

    assert view.last_four == "1234" and view.provider is Provider("anthropic")
    (stored,) = uow.store.credentials.values()
    assert "sk-secret" not in stored.encrypted_api_key
    assert decrypt(stored.encrypted_api_key, context=str(owner)) == "sk-secret-1234"

    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-other-9999", base_url=None
    )
    assert len(uow.store.credentials) == 1
    await identity.delete_credential(owner)
    with pytest.raises(CredentialMissingError):
        await identity.load(owner)


async def test_a_failed_key_pauses_the_user_and_is_announced() -> None:
    uow = FakeIdentityUnitOfWork()
    auth, identity = _auth(uow), _identity(uow)
    session = await auth.register(email="ada@example.com", password=PASSWORD)
    owner = session.account_id
    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-secret-1234", base_url=None
    )

    await identity.mark_failed(owner, "401 from provider")

    failed = await identity.credential(owner)
    assert failed is not None and failed.status is CredentialStatus.FAILED
    assert (await identity.account(owner)).background_jobs_paused
    assert uow.store.events == [
        ProviderCredentialFailed(owner_id=owner, reason="401 from provider")
    ]

    # A new key resumes the paused work.
    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-new-5678", base_url=None
    )
    assert not (await identity.account(owner)).background_jobs_paused


async def test_spending_past_the_cap_pauses_and_refuses() -> None:
    uow = FakeIdentityUnitOfWork()
    auth, identity = _auth(uow), _identity(uow)
    owner = (await auth.register(email="ada@example.com", password=PASSWORD)).account_id
    await identity.set_budget(owner, monthly_cap_usd=Decimal("1"))
    await identity.record(
        UsageRecord(
            owner_id=owner,
            task="assessment",
            provider="anthropic",
            model="claude",
            template_version="v1",
            input_tokens=10,
            output_tokens=10,
            cost_usd=Decimal("0.75"),
            estimated_input_tokens=12,
            estimated_cost_usd=Decimal("0.70"),
            is_estimated=False,
            funding=Funding.OWN,
        )
    )

    budget = await identity.budget(owner, today=datetime.now(UTC).date())
    assert budget.spent_this_month_usd == Decimal("0.75")
    await identity.check(owner, Decimal("0.2"), funding=Funding.OWN)
    with pytest.raises(BudgetExceededError):
        await identity.check(owner, Decimal("0.5"), funding=Funding.OWN)

    assert (await identity.account(owner)).background_jobs_paused
    assert uow.store.events == [
        UsageBudgetExceeded(
            owner_id=owner,
            cap_usd=Decimal("1"),
            spent_usd=Decimal("0.75"),
            estimated_usd=Decimal("0.5"),
        )
    ]


async def test_a_negative_cap_is_refused() -> None:
    with pytest.raises(ValidationError):
        await _identity(FakeIdentityUnitOfWork()).set_budget(
            uuid.uuid4(), monthly_cap_usd=Decimal("-1")
        )


async def test_the_cap_counts_only_what_the_users_own_key_paid_for() -> None:
    """The platform's spend is the operator's money, metered apart (ADR 0064)."""
    uow = FakeIdentityUnitOfWork()
    auth, identity = _auth(uow), _identity(uow)
    owner = (await auth.register(email="ada@example.com", password=PASSWORD)).account_id
    await identity.set_budget(owner, monthly_cap_usd=Decimal("1"))
    for funding, cost in ((Funding.OWN, "0.25"), (Funding.PLATFORM, "5.00")):
        await identity.record(
            UsageRecord(
                owner_id=owner,
                task="assessment",
                provider="anthropic",
                model="claude",
                template_version="v1",
                input_tokens=10,
                output_tokens=10,
                cost_usd=Decimal(cost),
                estimated_input_tokens=10,
                estimated_cost_usd=Decimal(cost),
                is_estimated=False,
                funding=funding,
            )
        )

    budget = await identity.budget(owner, today=datetime.now(UTC).date())
    assert budget.spent_this_month_usd == Decimal("0.25")
    # A platform call is not the user's cap to refuse.
    await identity.check(owner, Decimal("50"), funding=Funding.PLATFORM)
    assert not (await identity.account(owner)).background_jobs_paused


# --- which key AI runs on (ADR 0064) -----------------------------------------


def _platform_identity(uow: FakeIdentityUnitOfWork) -> IdentityService:
    return IdentityService(
        uow, default_monthly_cap_usd=Decimal("20"), platform_ai_model="claude-haiku-4-5"
    )


async def _google_account(uow: FakeIdentityUnitOfWork) -> uuid.UUID:
    owner = (await _auth(uow).register(email="ada@example.com", password=PASSWORD)).account_id
    identity = FederatedIdentity.linked(
        owner, provider="google", subject="google-sub-1", email="ada@example.com"
    )
    uow.store.federated[identity.id] = identity
    return owner


async def test_with_nothing_chosen_ai_runs_on_the_users_own_key_if_they_have_one() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)

    view = await identity.ai_source(owner)
    assert view.source is None and view.is_eligible and view.is_platform_on
    with pytest.raises(CredentialMissingError):
        await identity.load(owner)

    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-own-1234", base_url=None
    )
    assert (await identity.ai_source(owner)).source == AiSource.OWN
    assert not isinstance(await identity.load(owner), PlatformCredential)


async def test_a_google_account_switches_to_the_platform_once_it_accepts_the_terms() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)

    with pytest.raises(ValidationError, match="accept"):
        await identity.set_ai_source(owner, source="platform", accept_platform_terms=False)

    view = await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)
    assert view.source == AiSource.PLATFORM
    assert view.has_accepted_platform_terms
    assert view.platform_model == "claude-haiku-4-5"
    assert await identity.load(owner) == PlatformCredential(owner_id=owner)


async def test_switching_back_and_forth_asks_for_the_terms_only_once() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)
    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-own-1234", base_url=None
    )

    await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)
    await identity.set_ai_source(owner, source="own", accept_platform_terms=False)
    view = await identity.set_ai_source(owner, source="platform", accept_platform_terms=False)

    assert view.source == AiSource.PLATFORM


async def test_an_account_without_google_cannot_use_the_platforms_key() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = (await _auth(uow).register(email="bo@example.com", password=PASSWORD)).account_id

    assert not (await identity.ai_source(owner)).is_eligible
    with pytest.raises(PlatformAiNotEligibleError):
        await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)


async def test_losing_the_google_identity_stops_the_platforms_key_at_the_next_call() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)
    await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)

    uow.store.federated.clear()

    with pytest.raises(PlatformAiNotEligibleError):
        await identity.load(owner)


async def test_the_platform_cannot_be_chosen_while_it_is_off() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _identity(uow)
    owner = await _google_account(uow)

    assert not (await identity.ai_source(owner)).is_platform_on
    with pytest.raises(PlatformAiUnavailableError):
        await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)


async def test_ones_own_key_cannot_be_chosen_before_it_is_stored() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)

    with pytest.raises(ValidationError, match="key of your own"):
        await identity.set_ai_source(owner, source="own", accept_platform_terms=False)


async def test_switching_source_resumes_paused_work() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _platform_identity(uow)
    owner = await _google_account(uow)
    await identity.set_credential(
        owner, provider="anthropic", model="claude", api_key="sk-own-1234", base_url=None
    )
    await identity.mark_failed(owner, "401 from provider")
    assert (await identity.account(owner)).background_jobs_paused

    await identity.set_ai_source(owner, source="platform", accept_platform_terms=True)

    assert not (await identity.account(owner)).background_jobs_paused


# --- which endpoint a key may name (ADR 0065) ---------------------------------


async def test_only_an_openai_key_may_name_its_own_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hermetic: the SSRF guard would resolve the host. Its rules are tested
    # in tests/unit/kernel/fetch.
    from advisor.identity import service

    monkeypatch.setattr(service, "assert_public_url", lambda url: None)
    uow = FakeIdentityUnitOfWork()
    identity = _identity(uow)
    owner = (await _auth(uow).register(email="ada@example.com", password=PASSWORD)).account_id

    with pytest.raises(ValidationError, match="OpenAI-compatible"):
        await identity.set_credential(
            owner,
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key="sk-ant-1234",
            base_url="https://proxy.example.com",
        )

    view = await identity.set_credential(
        owner,
        provider="openai",
        model="llama-3.3-70b",
        api_key="gsk-1234",
        base_url="https://api.groq.com/openai/v1",
    )
    assert view.base_url == "https://api.groq.com/openai/v1"


async def test_a_self_hosted_model_is_not_a_provider() -> None:
    uow = FakeIdentityUnitOfWork()
    identity = _identity(uow)
    owner = (await _auth(uow).register(email="ada@example.com", password=PASSWORD)).account_id

    with pytest.raises(ValidationError, match="unknown provider"):
        await identity.set_credential(
            owner, provider="local", model="llama", api_key="k", base_url=None
        )


# --- a model with no published rate -------------------------------------------


async def test_a_model_with_no_published_rate_does_not_count_toward_the_cap() -> None:
    """Its cost is only our deliberately high guess; it must not pause work."""
    uow = FakeIdentityUnitOfWork()
    auth, identity = _auth(uow), _identity(uow)
    owner = (await auth.register(email="ada@example.com", password=PASSWORD)).account_id
    await identity.set_budget(owner, monthly_cap_usd=Decimal("1"))
    for is_rate_published, cost in ((True, "0.25"), (False, "9.00")):
        await identity.record(
            UsageRecord(
                owner_id=owner,
                task="assessment",
                provider="openai",
                model="llama-3.3-70b" if not is_rate_published else "gpt-5-mini",
                template_version="v1",
                input_tokens=10,
                output_tokens=10,
                cost_usd=Decimal(cost),
                estimated_input_tokens=10,
                estimated_cost_usd=Decimal(cost),
                is_estimated=False,
                funding=Funding.OWN,
                is_rate_published=is_rate_published,
            )
        )

    budget = await identity.budget(owner, today=datetime.now(UTC).date())
    assert budget.spent_this_month_usd == Decimal("0.25")
    # An unpriced call is never refused by the cap, however high its guess.
    await identity.check(owner, Decimal("50"), funding=Funding.OWN, is_priced=False)
    assert not (await identity.account(owner)).background_jobs_paused
