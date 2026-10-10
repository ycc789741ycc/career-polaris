"""The gateway's contract: budget first, schema always, ledger every call."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from kernel.ai_gateway import pricing, templates
from kernel.ai_gateway.gateway import AiGateway
from kernel.ai_gateway.ports import (
    BudgetGuard,
    CredentialStore,
    Funding,
    PlatformCredential,
    PlatformSpend,
    ProviderCredential,
    UsageRecord,
)
from kernel.ai_gateway.providers import (
    REGISTRY,
    Completion,
    Provider,
    Request,
    StreamEvent,
    TextDelta,
    Usage,
)
from kernel.config import InvalidConfigurationError, get_settings
from kernel.crypto import encrypt
from kernel.errors import (
    BudgetExceededError,
    CredentialFailedError,
    OutputInvalidError,
    PlatformAiCallTooLargeError,
    PlatformAiQuotaReachedError,
    PlatformAiUnavailableError,
)
from kernel.progress import WRITING_CAP, JobCancelledError, Progress

OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")


class Answer(BaseModel):
    name: str
    score: int


class StubCredentials(CredentialStore):
    def __init__(self, encrypted_key: str) -> None:
        self.failures: list[str] = []
        self._credential: ProviderCredential | PlatformCredential = ProviderCredential(
            provider="stub",
            model="claude-opus-5",
            base_url="https://llm.example.com",
            encrypted_api_key=encrypted_key,
            owner_id=OWNER,
        )

    async def load(self, owner_id: uuid.UUID) -> ProviderCredential | PlatformCredential:
        return self._credential

    def use_platform(self) -> None:
        self._credential = PlatformCredential(owner_id=OWNER)

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        self.failures.append(reason)


class StubBudget(BudgetGuard):
    def __init__(self, *, cap: Decimal | None = None) -> None:
        self.cap = cap
        self.recorded: list[UsageRecord] = []
        self.checked: list[Decimal] = []
        self.fundings: list[Funding] = []
        self.priced: list[bool] = []

    async def check(
        self,
        owner_id: uuid.UUID,
        estimated_cost_usd: Decimal,
        *,
        funding: Funding,
        is_priced: bool = True,
    ) -> None:
        self.checked.append(estimated_cost_usd)
        self.fundings.append(funding)
        self.priced.append(is_priced)
        if self.cap is not None and estimated_cost_usd > self.cap:
            raise BudgetExceededError("monthly cap would be exceeded", cap=str(self.cap))

    async def record(self, usage: UsageRecord) -> None:
        self.recorded.append(usage)


class StubProvider(Provider):
    name = "stub"
    default_base_url = "https://llm.example.com"

    def __init__(self, replies: list[str | Exception], usage: Usage | None = None) -> None:
        self.replies = list(replies)
        self.usage = usage
        self.requests: list[Request] = []
        self.closed = 0

    async def complete(self, client: object, request: Request) -> Completion:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply, input_tokens=120, output_tokens=40, model=request.model)

    async def stream(self, client: object, request: Request) -> AsyncGenerator[StreamEvent]:
        self.requests.append(request)
        try:
            for reply in self.replies:
                assert isinstance(reply, str)
                yield TextDelta(reply)
            if self.usage is not None:
                yield self.usage
        finally:
            self.closed += 1


class StubSpend(PlatformSpend):
    """The platform's meter, as calls in memory."""

    def __init__(self, *, refuse: Exception | None = None) -> None:
        self.refuse = refuse
        self.reserved: list[Decimal] = []
        self.spent: list[Decimal] = []
        self.released = 0

    async def create_reservation(self, owner_id: uuid.UUID, ceiling_usd: Decimal) -> object:
        if self.refuse is not None:
            raise self.refuse
        self.reserved.append(ceiling_usd)
        return "held"

    async def update_spent(self, reservation: object, cost_usd: Decimal) -> None:
        assert reservation == "held"
        self.spent.append(cost_usd)

    async def delete_reservation(self, reservation: object) -> None:
        assert reservation == "held"
        self.released += 1


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch):
    def install(replies: list[str | Exception], usage: Usage | None = None) -> StubProvider:
        provider = StubProvider(replies, usage)
        monkeypatch.setitem(REGISTRY, "stub", provider)
        return provider

    return install


@pytest.fixture
def gateway(clean_env: None) -> tuple[AiGateway, StubCredentials, StubBudget]:
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    budget = StubBudget()
    return (
        AiGateway(settings=get_settings(), credentials=credentials, budget=budget),
        (credentials),
        budget,
    )


TEMPLATE = templates.PromptTemplate(
    name="stub_task",
    version="v1",
    system="Return JSON.",
    user="Analyse {{subject}}.",
    expected_output_tokens=100,
)


async def test_valid_output_returns_value_with_model_and_template_version(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": "API design", "score": 81}'])

    result = await gw.run(
        OWNER,
        task="assess",
        template=TEMPLATE,
        inputs={"subject": "a backend engineer"},
        output_schema=Answer,
    )

    assert result.value == Answer(name="API design", score=81)
    assert result.model_id == "claude-opus-5"
    assert result.template_version == "stub_task@v1"
    assert len(budget.recorded) == 1


async def test_budget_is_checked_before_the_provider_is_called(
    clean_env: None, stub_provider
) -> None:
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    budget = StubBudget(cap=Decimal("0.0000001"))
    gw = AiGateway(settings=get_settings(), credentials=credentials, budget=budget)
    provider = stub_provider(['{"name": "x", "score": 1}'])

    with pytest.raises(BudgetExceededError):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
        )
    assert provider.requests == [], "no money may be spent once the cap is hit"


async def test_output_that_misses_the_schema_is_retried_then_rejected(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": "x"}', "not json at all", '{"score": "high"}'])

    with pytest.raises(OutputInvalidError, match="after 3 attempts"):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
        )

    assert len(provider.requests) == 3
    assert len(budget.recorded) == 3, "the provider billed for every attempt, so log every attempt"


async def test_a_retry_tells_the_model_what_was_wrong(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    provider = stub_provider(["nonsense", '{"name": "API design", "score": 81}'])

    result = await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert result.value.score == 81
    assert "could not be used" in provider.requests[1].user
    assert '<data name="validation_error">' in provider.requests[1].user


async def test_json_wrapped_in_a_code_fence_is_accepted(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider(['Here you go:\n```json\n{"name": "API design", "score": 81}\n```'])
    result = await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )
    assert result.value.name == "API design"


async def test_a_rejected_key_is_reported_and_pauses_the_user(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, credentials, _ = gateway
    stub_provider([CredentialFailedError("the provider rejected this API key")])

    with pytest.raises(CredentialFailedError):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
        )
    assert credentials.failures == ["the provider rejected this API key"]


async def test_the_decrypted_key_reaches_the_provider_and_nothing_else(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": "x", "score": 1}'])

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert provider.requests[0].api_key == "sk-test-key"
    assert "sk-test-key" not in str(budget.recorded[0])


async def test_estimate_prices_a_call_without_making_one(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider([])

    estimate = await gw.estimate(OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"})

    assert estimate.cost_usd > 0
    assert estimate.model_id == "claude-opus-5"
    assert estimate.rate_is_published is True
    assert provider.requests == [] and budget.recorded == []


# -- structured streaming (the résumé chat) ---------------------------------

MARKER = "<<<PROPOSAL>>>"


async def _collect(gw: AiGateway) -> tuple[str, list[Any]]:
    from kernel.ai_gateway import StreamResult, StreamText

    text: str = ""
    results: list[Any] = []
    async for event in gw.stream_structured(
        OWNER,
        task="revise",
        template=TEMPLATE,
        inputs={"subject": "a résumé"},
        output_schema=Answer,
        marker=MARKER,
    ):
        if isinstance(event, StreamText):
            text += event.text
        else:
            assert isinstance(event, StreamResult)
            results.append(event)
    return text, results


async def test_prose_streams_and_the_object_after_the_marker_is_validated(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(["Shorter summary, ", "sharper lead.\n", MARKER, '{"name": "x", "score": 3}'])

    text, results = await _collect(gw)

    assert text == "Shorter summary, sharper lead.\n"
    [result] = results
    assert result.value == Answer(name="x", score=3)
    assert result.template_version == "stub_task@v1"
    assert len(budget.recorded) == 1


async def test_a_marker_split_across_chunks_never_leaks_to_the_reader(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider(["Done. <<<PRO", "POSAL>>>", '{"name": "y", "score": 1}'])

    text, results = await _collect(gw)

    assert text == "Done. "
    assert "<" not in text
    assert len(results) == 1


async def test_text_that_only_looks_like_the_start_of_the_marker_is_released(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider(["a << b", " and more", MARKER, '{"name": "z", "score": 2}'])

    text, _ = await _collect(gw)

    assert text == "a << b and more"


async def test_a_reply_with_no_structured_part_is_rejected_after_its_text(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider(["Just advice, no proposal."])

    with pytest.raises(OutputInvalidError, match="without its structured part"):
        await _collect(gw)


async def test_an_invalid_structured_part_is_rejected_without_a_retry(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    provider = stub_provider(["Here.", MARKER, '{"name": "x"}'])

    with pytest.raises(OutputInvalidError, match="did not match the schema"):
        await _collect(gw)
    assert len(provider.requests) == 1


# -- progress while a job's call streams (ADR 0042) ----------------------------


@pytest.fixture
def ticking_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read of the clock is three seconds on, so each chunk reports."""
    from kernel.ai_gateway import gateway as gateway_module

    now = iter(range(0, 10_000, 3))
    monkeypatch.setattr(gateway_module, "_clock", lambda: float(next(now)))


async def test_a_streamed_call_reports_its_share_capped_until_checked(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider, ticking_clock: None
) -> None:
    gw, _, budget = gateway
    # Far more text than the template expects: the share stops at the cap.
    stub_provider(['{"name": "API design", ', '"score": 81}', " " * 2000])
    seen: list[Progress] = []

    async def report(progress: Progress) -> None:
        seen.append(progress)

    result = await gw.run(
        OWNER,
        task="assess",
        template=TEMPLATE,
        inputs={"subject": "a backend engineer"},
        output_schema=Answer,
        on_progress=report,
    )

    assert result.value == Answer(name="API design", score=81)
    fractions = [p.fraction for p in seen]
    assert fractions[0] == 0.0
    assert fractions == sorted(fractions)
    assert max(fractions) == WRITING_CAP
    assert all(p.estimated_cost_usd == budget.checked[0] for p in seen)
    assert len(budget.recorded) == 1


async def test_a_job_cancelled_before_its_call_sends_nothing(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": "API design", "score": 81}'])

    async def cancelled(progress: Progress) -> None:
        raise JobCancelledError

    with pytest.raises(JobCancelledError):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
            on_progress=cancelled,
        )
    assert provider.requests == [] and budget.recorded == []


async def test_a_job_cancelled_while_it_streams_stops_and_is_still_charged(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider, ticking_clock: None
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": ', '"API design", ', '"score": 81}'])

    async def cancel_once_writing(progress: Progress) -> None:
        if progress.fraction > 0:
            raise JobCancelledError

    with pytest.raises(JobCancelledError):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
            on_progress=cancel_once_writing,
        )
    # What was written before the stop is billed, so the ledger has it.
    [usage] = budget.recorded
    assert usage.output_tokens > 0


# -- what the ledger records ---------------------------------------------------


async def test_a_streamed_call_is_recorded_with_the_providers_counts(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(
        ['{"name": "API design", "score": 81}'],
        usage=Usage(input_tokens=1_840, output_tokens=612, model="claude-opus-5-20261001"),
    )

    async def report(progress: Progress) -> None:
        pass

    await gw.run(
        OWNER,
        task="assess",
        template=TEMPLATE,
        inputs={"subject": "x"},
        output_schema=Answer,
        on_progress=report,
    )

    [usage] = budget.recorded
    assert (usage.input_tokens, usage.output_tokens) == (1_840, 612)
    assert usage.is_estimated is False
    # Kept as reported, priced as asked: the dated id has no rate of its own.
    assert usage.model == "claude-opus-5-20261001"
    assert usage.cost_usd == pricing.cost_of("claude-opus-5", input_tokens=1_840, output_tokens=612)
    assert usage.estimated_input_tokens > 0
    assert usage.estimated_cost_usd == budget.checked[0]


async def test_a_stream_that_reports_no_usage_is_recorded_as_estimated(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": "API design", "score": 81}'])

    async def report(progress: Progress) -> None:
        pass

    await gw.run(
        OWNER,
        task="assess",
        template=TEMPLATE,
        inputs={"subject": "x"},
        output_schema=Answer,
        on_progress=report,
    )

    [usage] = budget.recorded
    assert usage.is_estimated is True
    assert usage.output_tokens == pricing.estimate_tokens('{"name": "API design", "score": 81}')


async def test_a_cancelled_stream_is_closed_and_recorded_as_estimated(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider, ticking_clock: None
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": ', '"API design", ', '"score": 81}'])

    async def cancel_once_writing(progress: Progress) -> None:
        if progress.fraction > 0:
            raise JobCancelledError

    with pytest.raises(JobCancelledError):
        await gw.run(
            OWNER,
            task="assess",
            template=TEMPLATE,
            inputs={"subject": "x"},
            output_schema=Answer,
            on_progress=cancel_once_writing,
        )

    assert provider.closed == 1, "stopping must close the connection, so the provider stops"
    [usage] = budget.recorded
    assert usage.is_estimated is True


async def test_a_chat_reader_that_stops_early_still_pays_for_what_was_written(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(["First part. ", "Second part. ", "Third part."])

    events = gw.stream(OWNER, task="revise", template=TEMPLATE, inputs={"subject": "x"})
    first = await anext(events)
    await events.aclose()

    assert first == "First part. "
    assert provider.closed == 1
    [usage] = budget.recorded
    assert usage.is_estimated is True and usage.output_tokens > 0


async def test_a_finished_chat_is_recorded_with_the_providers_counts(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(
        ["All ", "done."], usage=Usage(input_tokens=500, output_tokens=7, model="claude-opus-5")
    )

    text = "".join(
        [
            chunk
            async for chunk in gw.stream(
                OWNER, task="revise", template=TEMPLATE, inputs={"subject": "x"}
            )
        ]
    )

    assert text == "All done."
    [usage] = budget.recorded
    assert (usage.input_tokens, usage.output_tokens, usage.is_estimated) == (500, 7, False)


async def test_the_ceiling_covers_every_attempt_at_its_output_limit(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider([])

    estimate = await gw.estimate(OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"})

    attempts = get_settings().ai_max_output_retries + 1
    # TEMPLATE expects 100 tokens; a call may write up to 4,096.
    floor = pricing.cost_of("claude-opus-5", input_tokens=0, output_tokens=attempts * 4_096)
    assert estimate.ceiling_cost_usd >= floor
    assert estimate.ceiling_cost_usd > estimate.cost_usd * attempts


# -- the platform's key (ADR 0064) ---------------------------------------------


@pytest.fixture
def platform_env(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_AI_API_KEY", "sk-platform-key")
    monkeypatch.setenv("PLATFORM_AI_PROVIDER", "stub-platform")
    monkeypatch.setenv("PLATFORM_AI_MODEL", "claude-haiku-4-5")
    get_settings.cache_clear()


@pytest.fixture
def platform_provider(monkeypatch: pytest.MonkeyPatch, stub_provider):
    """The platform's provider, registered under a name settings accept."""
    from kernel import config

    monkeypatch.setattr(config, "PLATFORM_AI_PROVIDERS", ("stub-platform",))

    def install(replies: list[str | Exception]) -> StubProvider:
        provider = StubProvider(replies)
        monkeypatch.setitem(REGISTRY, "stub-platform", provider)
        return provider

    return install


async def test_a_platform_call_runs_on_the_platforms_key_and_model(
    platform_provider, platform_env: None
) -> None:
    provider = platform_provider(['{"name": "x", "score": 1}'])
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    credentials.use_platform()
    budget = StubBudget()
    gw = AiGateway(
        settings=get_settings(), credentials=credentials, budget=budget, platform_spend=StubSpend()
    )

    result = await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert provider.requests[0].api_key == "sk-platform-key"
    assert provider.requests[0].model == "claude-haiku-4-5"
    assert result.model_id == "claude-haiku-4-5"
    assert budget.fundings == [Funding.PLATFORM]
    [usage] = budget.recorded
    assert usage.funding is Funding.PLATFORM
    assert "sk-platform-key" not in str(usage)


async def test_the_users_own_key_is_recorded_as_their_own(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": "x", "score": 1}'])

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert budget.fundings == [Funding.OWN]
    assert budget.recorded[0].funding is Funding.OWN


async def test_the_platforms_key_failing_leaves_the_users_state_alone(
    platform_provider, platform_env: None
) -> None:
    platform_provider([CredentialFailedError("the provider rate-limited this key")])
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    credentials.use_platform()
    gw = AiGateway(
        settings=get_settings(),
        credentials=credentials,
        budget=StubBudget(),
        platform_spend=StubSpend(),
    )

    with pytest.raises(PlatformAiUnavailableError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
        )
    assert credentials.failures == [], "our key failing must not pause the user's work"


async def test_a_platform_call_with_the_feature_off_is_refused(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, credentials, budget = gateway
    provider = stub_provider([])
    credentials.use_platform()

    with pytest.raises(PlatformAiUnavailableError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
        )
    assert provider.requests == [] and budget.checked == []


async def test_an_estimate_says_whose_key_it_would_run_on(
    platform_provider, platform_env: None
) -> None:
    platform_provider([])
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    credentials.use_platform()
    gw = AiGateway(
        settings=get_settings(),
        credentials=credentials,
        budget=StubBudget(),
        platform_spend=StubSpend(),
    )

    estimate = await gw.estimate(OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"})

    assert estimate.funding is Funding.PLATFORM
    assert estimate.model_id == "claude-haiku-4-5"


def test_a_platform_model_with_no_published_rate_refuses_to_start(
    platform_provider, platform_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_AI_MODEL", "some-model-we-cannot-price")
    get_settings.cache_clear()

    with pytest.raises(InvalidConfigurationError, match="no published rate"):
        AiGateway(
            settings=get_settings(),
            credentials=StubCredentials(""),
            budget=StubBudget(),
            platform_spend=StubSpend(),
        )


def test_a_platform_key_with_nothing_to_meter_it_refuses_to_start(
    platform_provider, platform_env: None
) -> None:
    with pytest.raises(InvalidConfigurationError, match="meters"):
        AiGateway(settings=get_settings(), credentials=StubCredentials(""), budget=StubBudget())


def _platform_gateway(spend: StubSpend) -> tuple[AiGateway, StubCredentials, StubBudget]:
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    credentials.use_platform()
    budget = StubBudget()
    gateway = AiGateway(
        settings=get_settings(), credentials=credentials, budget=budget, platform_spend=spend
    )
    return gateway, credentials, budget


async def test_a_platform_call_reserves_its_ceiling_settles_each_attempt_and_releases(
    platform_provider, platform_env: None
) -> None:
    platform_provider(["not json", '{"name": "x", "score": 1}'])
    spend = StubSpend()
    gw, _, budget = _platform_gateway(spend)

    estimate = await gw.estimate(OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"})
    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert spend.reserved == [estimate.ceiling_cost_usd]
    assert spend.spent == [usage.cost_usd for usage in budget.recorded]
    assert len(spend.spent) == 2
    assert spend.released == 1


async def test_a_failed_platform_call_still_releases_what_it_held(
    platform_provider, platform_env: None
) -> None:
    platform_provider(["no", "no", "no"])
    spend = StubSpend()
    gw, _, _ = _platform_gateway(spend)

    with pytest.raises(OutputInvalidError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
        )
    assert len(spend.spent) == 3
    assert spend.released == 1


async def test_a_platform_call_with_no_room_is_never_sent(
    platform_provider, platform_env: None
) -> None:
    provider = platform_provider(['{"name": "x", "score": 1}'])
    spend = StubSpend(refuse=PlatformAiQuotaReachedError("You have used this month's AI."))
    gw, _, budget = _platform_gateway(spend)

    with pytest.raises(PlatformAiQuotaReachedError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
        )
    assert provider.requests == [] and budget.recorded == []


async def test_a_platform_call_too_large_for_one_call_is_refused_before_it_holds_anything(
    platform_provider, platform_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_AI_MAX_CALL_USD", "0.0001")
    get_settings.cache_clear()
    provider = platform_provider(['{"name": "x", "score": 1}'])
    spend = StubSpend()
    gw, _, _ = _platform_gateway(spend)

    with pytest.raises(PlatformAiCallTooLargeError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
        )
    assert provider.requests == [] and spend.reserved == []


async def test_a_platform_chat_that_stops_early_settles_and_releases(
    platform_provider, platform_env: None
) -> None:
    platform_provider(["First. ", "Second."])
    spend = StubSpend()
    gw, _, _ = _platform_gateway(spend)

    events = gw.stream(OWNER, task="revise", template=TEMPLATE, inputs={"subject": "x"})
    await anext(events)
    await events.aclose()

    assert len(spend.spent) == 1 and spend.released == 1


async def test_the_users_own_key_holds_nothing_on_the_platforms_meter(
    clean_env: None, stub_provider
) -> None:
    stub_provider(['{"name": "x", "score": 1}'])
    spend = StubSpend()
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    gw = AiGateway(
        settings=get_settings(), credentials=credentials, budget=StubBudget(), platform_spend=spend
    )

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert spend.reserved == [] and spend.spent == [] and spend.released == 0


# -- a model with no published rate -------------------------------------------


async def test_a_model_with_no_published_rate_is_recorded_and_checked_as_unpriced(
    clean_env: None, stub_provider
) -> None:
    stub_provider(['{"name": "x", "score": 1}'])
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    credentials._credential = ProviderCredential(
        provider="stub",
        model="llama-3.3-70b",
        base_url="https://llm.example.com",
        encrypted_api_key=encrypt("sk-test-key", context=str(OWNER)),
        owner_id=OWNER,
    )
    budget = StubBudget()
    gw = AiGateway(settings=get_settings(), credentials=credentials, budget=budget)

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert budget.priced == [False]
    [usage] = budget.recorded
    assert usage.is_rate_published is False


async def test_a_priced_model_is_recorded_as_priced(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": "x", "score": 1}'])

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert budget.priced == [True]
    assert budget.recorded[0].is_rate_published is True
