"""The only path to an LLM in this system.

    estimate cost -> within budget? -> decrypt credential -> provider adapter
    -> validate against output schema -> write usage ledger -> return result

Used by ``api`` (streaming chat, from Phase 3) and by ``worker`` jobs. Modules
never import a provider adapter directly; an import-linter contract enforces
that (docs/architecture.md section 5).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, SecretStr
from pydantic import ValidationError as PydanticValidationError

from kernel.ai_gateway import pricing, templates
from kernel.ai_gateway.ports import (
    BudgetGuard,
    CredentialStore,
    Funding,
    PlatformCredential,
    PlatformSpend,
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
from kernel.ai_gateway.templates import PromptTemplate
from kernel.config import InvalidConfigurationError, Settings
from kernel.crypto import decrypt
from kernel.errors import (
    CredentialFailedError,
    DomainError,
    OutputInvalidError,
    PlatformAiCallTooLargeError,
    PlatformAiUnavailableError,
    ProviderUnavailableError,
    ValidationError,
)
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from kernel.progress import (
    REPORT_EVERY_SECONDS,
    WRITING_CAP,
    JobCancelledError,
    Progress,
    ProgressCallback,
)

T = TypeVar("T", bound=BaseModel)

# Read through a name of its own, so a test can move it without moving the
# event loop's clock.
_clock = time.monotonic

log = get_logger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_MIN_OUTPUT_TOKENS = 4_096
_MAX_OUTPUT_TOKENS = 16_000
# Long enough for a schema error to be useful, short enough for the ceiling.
_REPAIR_PROBLEM_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class Result[TModel: BaseModel]:
    """A validated answer, plus what produced it.

    ``model_id`` and ``template_version`` are stored on every AI-derived
    snapshot so a user who switches models can be shown why results changed
    (domain section 2.8).
    """

    value: TModel
    model_id: str
    template_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class StreamText:
    """Prose from a structured stream, safe to show as it arrives."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamResult[TModel: BaseModel]:
    """The validated object that ends a structured stream."""

    value: TModel
    model_id: str
    template_version: str


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a call would cost, before any money is spent."""

    input_tokens: int
    expected_output_tokens: int
    cost_usd: Decimal
    model_id: str
    template_version: str
    rate_is_published: bool
    # Whose key it would run on.
    funding: Funding
    # The most it can cost: every retry, each to its output limit
    # (``pricing.estimate_ceiling``). Money that is not the user's is
    # reserved against this.
    ceiling_cost_usd: Decimal


class AiGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        credentials: CredentialStore,
        budget: BudgetGuard,
        platform_spend: PlatformSpend | None = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._budget = budget
        self._platform_spend = platform_spend
        if settings.platform_ai_enabled:
            if platform_spend is None:
                raise InvalidConfigurationError(
                    "the platform's AI key is set, but nothing meters what it spends"
                )
            model = settings.platform_ai_model or ""
            # The platform's spend is metered against these rates; a guessed
            # one would make every quota wrong.
            if not pricing.rate_for(model).is_published:
                raise InvalidConfigurationError(
                    f"PLATFORM_AI_MODEL {model!r} has no published rate in pricing.json"
                )

    # -- internals ----------------------------------------------------------

    def _client(self) -> GuardedClient:
        return GuardedClient(
            timeout_seconds=self._settings.ai_request_timeout_seconds,
            user_agent=self._settings.service_name,
        )

    @property
    def _attempts(self) -> int:
        return self._settings.ai_max_output_retries + 1

    async def _resolve(self, owner_id: uuid.UUID) -> _Key:
        """The key this user's call runs on: their own, still encrypted, or
        the platform's, which only the gateway holds."""
        credential = await self._credentials.load(owner_id)
        if isinstance(credential, PlatformCredential):
            settings = self._settings
            if settings.platform_ai_api_key is None:
                raise PlatformAiUnavailableError(
                    "CareerPolaris's AI is switched off; add a key of your own to continue"
                )
            provider_name = settings.platform_ai_provider or ""
            return _Key(
                owner_id=owner_id,
                provider=REGISTRY[provider_name],
                model=settings.platform_ai_model or "",
                base_url=REGISTRY[provider_name].default_base_url,
                funding=Funding.PLATFORM,
                platform_key=settings.platform_ai_api_key,
            )
        provider = REGISTRY.get(credential.provider)
        if provider is None:
            raise ValidationError(
                f"unknown AI provider {credential.provider!r}", provider=credential.provider
            )
        base_url = credential.base_url or provider.default_base_url
        if not base_url:
            raise ValidationError("this provider needs a base URL", provider=credential.provider)
        return _Key(
            owner_id=owner_id,
            provider=provider,
            model=credential.model,
            base_url=base_url,
            funding=Funding.OWN,
            encrypted_api_key=credential.encrypted_api_key,
        )

    async def _prepare(
        self,
        owner_id: uuid.UUID,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str],
    ) -> tuple[_Key, Request, pricing.CostEstimate]:
        key = await self._resolve(owner_id)
        prompt = template.render(inputs, untrusted=untrusted)
        estimate = pricing.estimate(
            key.model,
            prompt=template.system + prompt,
            expected_output_tokens=template.expected_output_tokens,
        )
        request = Request(
            # The key is opened here and lives only for this call.
            api_key=key.get_api_key(),
            model=key.model,
            base_url=key.base_url,
            system=template.system,
            user=prompt,
            max_output_tokens=_max_output_tokens(template),
        )
        return key, request, estimate

    async def _fail_key(self, key: _Key, error: DomainError) -> Exception:
        """What a provider refusing the key becomes.

        The user's own key is marked failed and their jobs paused. The
        platform's failing is ours, not theirs: it is logged for the operator
        and the user is told it is unavailable, with nothing of theirs changed.
        """
        if key.funding is Funding.OWN:
            await self._credentials.mark_failed(key.owner_id, error.message)
            return error
        log.error("ai.platform_key_failed", reason=error.message, provider=key.provider.name)
        return PlatformAiUnavailableError(
            "CareerPolaris's AI is unavailable right now; try again later or use your own key"
        )

    async def _record(
        self,
        key: _Key,
        *,
        task: str,
        template: PromptTemplate,
        request: Request,
        completion: Completion,
        reservation: object | None,
    ) -> Decimal:
        """Write one attempt to the ledger, beside what it was estimated at.

        Priced at the rate of the model we asked for: a provider may answer
        an alias with a dated snapshot id, which the ledger keeps as reported.
        """
        estimate = pricing.estimate(
            request.model,
            prompt=request.system + request.user,
            expected_output_tokens=template.expected_output_tokens,
        )
        cost = pricing.cost_of(
            request.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
        await self._budget.record(
            UsageRecord(
                owner_id=key.owner_id,
                task=task,
                provider=key.provider.name,
                model=completion.model,
                template_version=template.version_id,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                cost_usd=cost,
                estimated_input_tokens=estimate.input_tokens,
                estimated_cost_usd=estimate.cost_usd,
                is_estimated=completion.is_estimated,
                funding=key.funding,
            )
        )
        if reservation is not None and self._platform_spend is not None:
            await self._platform_spend.update_spent(reservation, cost)
            log.info(
                "platform_ai.spend",
                task=task,
                cost_usd=str(cost),
                is_estimated=completion.is_estimated,
            )
        return cost

    async def _create_reservation(self, key: _Key, request: Request) -> object | None:
        """Hold the most a platform call can cost, before it is sent.

        Nothing is held for the user's own key: their cap is checked against
        the typical estimate, as it always was.
        """
        if key.funding is Funding.OWN:
            return None
        if self._platform_spend is None:
            raise PlatformAiUnavailableError("CareerPolaris's AI is switched off")
        ceiling = pricing.estimate_ceiling(
            key.model,
            prompt=request.system + request.user,
            max_output_tokens=request.max_output_tokens,
            attempts=self._attempts,
        ).cost_usd
        most = Decimal(str(self._settings.platform_ai_max_call_usd))
        if ceiling > most:
            raise PlatformAiCallTooLargeError(
                "This is too large to run on CareerPolaris's AI; use your own key for it",
                ceiling_usd=str(ceiling),
            )
        return await self._platform_spend.create_reservation(key.owner_id, ceiling)

    async def _delete_reservation(self, reservation: object | None) -> None:
        if reservation is not None and self._platform_spend is not None:
            await self._platform_spend.delete_reservation(reservation)

    # -- public surface -----------------------------------------------------

    async def estimate(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str] = frozenset(),
    ) -> Estimate:
        """Price a call without making it.

        This is what the first-analysis and first-role-map confirmations show.
        """
        key = await self._resolve(owner_id)
        prompt = template.system + template.render(inputs, untrusted=untrusted)
        cost = pricing.estimate(
            key.model,
            prompt=prompt,
            expected_output_tokens=template.expected_output_tokens,
        )
        ceiling = pricing.estimate_ceiling(
            key.model,
            prompt=prompt,
            max_output_tokens=_max_output_tokens(template),
            attempts=self._attempts,
        )
        log.info(
            "ai.estimate",
            task=task,
            template=template.version_id,
            model=key.model,
            funding=str(key.funding),
        )
        return Estimate(
            input_tokens=cost.input_tokens,
            expected_output_tokens=cost.output_tokens,
            cost_usd=cost.cost_usd,
            model_id=key.model,
            template_version=template.version_id,
            rate_is_published=cost.rate_is_published,
            funding=key.funding,
            ceiling_cost_usd=ceiling.cost_usd,
        )

    async def run(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        output_schema: type[T],
        untrusted: frozenset[str] = frozenset(),
        on_progress: ProgressCallback | None = None,
    ) -> Result[T]:
        """One call, validated against ``output_schema``, retried with a
        repair note when it is not.

        With ``on_progress`` the reply is streamed, and the callback hears how
        far it has got (ADR 0042): once before each attempt is sent, then at
        most every ``REPORT_EVERY_SECONDS``. It may raise to stop the call
        where it is, which closes the connection; what was written by then is
        recorded, as it is billed. Every attempt is recorded with the token
        counts the provider reported, or an estimate marked as one when it
        reported none.
        """
        key, request, estimate = await self._prepare(owner_id, template, inputs, untrusted)
        await self._budget.check(owner_id, estimate.cost_usd, funding=key.funding)
        provider = key.provider
        last_error: Exception | None = None
        reservation = await self._create_reservation(key, request)
        try:
            async with self._client() as client:
                for attempt in range(self._attempts):
                    try:
                        if on_progress is None:
                            completion = await provider.complete(client, request)
                        else:
                            completion = await self._complete_streamed(
                                key,
                                client,
                                request,
                                task=task,
                                template=template,
                                estimate=estimate,
                                on_progress=on_progress,
                                reservation=reservation,
                            )
                    except CredentialFailedError as exc:
                        raise await self._fail_key(key, exc) from exc
                    except ProviderUnavailableError:
                        raise

                    # The ledger records every call, including one whose output we
                    # then reject — the provider billed for it either way.
                    cost = await self._record(
                        key,
                        task=task,
                        template=template,
                        request=request,
                        completion=completion,
                        reservation=reservation,
                    )

                    try:
                        value = _parse(completion.text, output_schema)
                    except OutputInvalidError as exc:
                        last_error = exc
                        log.warning(
                            "ai.output_invalid",
                            task=task,
                            template=template.version_id,
                            attempt=attempt + 1,
                        )
                        request = _with_repair_note(request, str(exc))
                        continue

                    return Result(
                        value=value,
                        model_id=completion.model,
                        template_version=template.version_id,
                        input_tokens=completion.input_tokens,
                        output_tokens=completion.output_tokens,
                        cost_usd=cost,
                    )

            raise OutputInvalidError(
                f"{task}: the model did not return output matching the schema after "
                f"{self._attempts} attempts",
                task=task,
                template=template.version_id,
            ) from last_error
        finally:
            await self._delete_reservation(reservation)

    async def _complete_streamed(
        self,
        key: _Key,
        client: GuardedClient,
        request: Request,
        *,
        task: str,
        template: PromptTemplate,
        estimate: pricing.CostEstimate,
        on_progress: ProgressCallback,
        reservation: object | None,
    ) -> Completion:
        """One attempt, streamed, reporting its share of the expected output.
        A callback that raises stops it and closes the connection; what was
        written so far is recorded in the ledger before the error goes on."""
        await on_progress(Progress(fraction=0.0, estimated_cost_usd=estimate.cost_usd))
        expected = max(template.expected_output_tokens, 1)
        tally = _Tally()
        last_report = _clock()
        try:
            async with aclosing(key.provider.stream(client, request)) as events:
                async for event in events:
                    if tally.add(event) is None:
                        continue
                    now = _clock()
                    if now - last_report >= REPORT_EVERY_SECONDS:
                        last_report = now
                        written = pricing.estimate_tokens(tally.text)
                        await on_progress(
                            Progress(
                                fraction=min(written / expected, WRITING_CAP),
                                estimated_cost_usd=estimate.cost_usd,
                            )
                        )
        except JobCancelledError:
            if tally.parts:
                await self._record(
                    key,
                    task=task,
                    template=template,
                    request=request,
                    completion=tally.get_completion(request, is_cut_short=True),
                    reservation=reservation,
                )
            raise
        return tally.get_completion(request, is_cut_short=False)

    async def stream(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str] = frozenset(),
    ) -> AsyncGenerator[str]:
        """Token-by-token output, for the resume chat.

        Budget and credential handling are identical to :meth:`run`; only
        schema validation is absent, because the caller is rendering text.
        A reader that stops early closes the connection, and what was written
        by then is still recorded.
        """
        key, request, estimate = await self._prepare(owner_id, template, inputs, untrusted)
        await self._budget.check(owner_id, estimate.cost_usd, funding=key.funding)
        reservation = await self._create_reservation(key, request)
        try:
            tally = _Tally()
            is_finished = False
            async with self._client() as client:
                try:
                    async with aclosing(key.provider.stream(client, request)) as events:
                        async for event in events:
                            piece = tally.add(event)
                            if piece is not None:
                                yield piece
                    is_finished = True
                except CredentialFailedError as exc:
                    raise await self._fail_key(key, exc) from exc
                finally:
                    if is_finished or tally.parts:
                        await self._record(
                            key,
                            task=task,
                            template=template,
                            request=request,
                            completion=tally.get_completion(request, is_cut_short=not is_finished),
                            reservation=reservation,
                        )
        finally:
            await self._delete_reservation(reservation)

    async def stream_structured(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        output_schema: type[T],
        marker: str,
        untrusted: frozenset[str] = frozenset(),
    ) -> AsyncIterator[StreamText | StreamResult[T]]:
        """Prose as it arrives, then one validated object.

        The template asks for the reply followed by ``marker`` and a JSON
        object. Text before the marker streams to the caller; the marker never
        does. The JSON is validated against ``output_schema`` exactly as
        :meth:`run` would, and ends the stream as a :class:`StreamResult`.

        There is no retry: the prose has already been shown, so a second
        attempt would contradict it. Invalid output raises
        ``OutputInvalidError`` after the text.
        """
        key = await self._resolve(owner_id)
        pending = ""
        tail: str | None = None
        async for chunk in self.stream(
            owner_id, task=task, template=template, inputs=inputs, untrusted=untrusted
        ):
            if tail is not None:
                tail += chunk
                continue
            release, tail = _split_at_marker(pending + chunk, marker)
            pending = "" if tail is not None else (pending + chunk)[len(release) :]
            if release:
                yield StreamText(release)
        if tail is None:
            if pending:
                yield StreamText(pending)
            raise OutputInvalidError("the reply ended without its structured part")
        yield StreamResult(
            value=_parse(tail, output_schema),
            model_id=key.model,
            template_version=template.version_id,
        )


@dataclass(frozen=True, slots=True)
class _Key:
    """The key one call runs on, still closed.

    The user's own is encrypted, bound to their id; the platform's is a
    ``SecretStr`` from settings. ``get_api_key`` opens either, once, for the
    request that sends it.
    """

    owner_id: uuid.UUID
    provider: Provider
    model: str
    base_url: str
    funding: Funding
    encrypted_api_key: str | None = None
    platform_key: SecretStr | None = None

    def get_api_key(self) -> str:
        if self.platform_key is not None:
            return self.platform_key.get_secret_value()
        if self.encrypted_api_key is None:
            raise ValidationError("this call has no key to run on")
        return decrypt(self.encrypted_api_key, context=str(self.owner_id))


def _max_output_tokens(template: PromptTemplate) -> int:
    return min(_MAX_OUTPUT_TOKENS, max(_MIN_OUTPUT_TOKENS, template.expected_output_tokens * 2))


@dataclass(slots=True)
class _Tally:
    """What one streamed attempt has written and used so far."""

    parts: list[str] = field(default_factory=list)
    usage: Usage | None = None

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def add(self, event: StreamEvent) -> str | None:
        """Take one event; the text it carries, if any."""
        if isinstance(event, TextDelta):
            self.parts.append(event.text)
            return event.text
        self.usage = event
        return None

    def get_completion(self, request: Request, *, is_cut_short: bool) -> Completion:
        """The attempt as the ledger records it.

        The provider's counts when it reported them for the whole reply.
        Otherwise, or when the reply was cut short, the counts are estimated
        and marked so; an input count the provider sent first is still used.
        """
        text = self.text
        usage = self.usage
        if usage is not None and not is_cut_short:
            return Completion(
                text=text,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                model=usage.model,
            )
        input_tokens = (
            usage.input_tokens
            if usage is not None and usage.input_tokens > 0
            else pricing.estimate_tokens(request.system + request.user)
        )
        output_tokens = max(
            usage.output_tokens if usage is not None else 0, pricing.estimate_tokens(text)
        )
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=usage.model if usage is not None else request.model,
            is_estimated=True,
        )


def _split_at_marker(buffer: str, marker: str) -> tuple[str, str | None]:
    """Text safe to release now, and what follows the marker if it has come.

    Text is held back while it could still be the start of the marker, so no
    part of the marker ever reaches the reader.
    """
    at = buffer.find(marker)
    if at >= 0:
        return buffer[:at], buffer[at + len(marker) :]
    for keep in range(min(len(marker) - 1, len(buffer)), 0, -1):
        if marker.startswith(buffer[-keep:]):
            return buffer[:-keep], None
    return buffer, None


def _parse[TOut: BaseModel](text: str, schema: type[TOut]) -> TOut:
    """Turn model output into a validated object, or reject it.

    Output is untrusted like any other external text, so nothing is used before
    it validates.
    """
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        # Some models prepend a sentence before the object.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start > 0 and end > start:
            candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except ValueError as exc:
        raise OutputInvalidError("model output was not JSON") from exc

    try:
        return schema.model_validate(payload)
    except PydanticValidationError as exc:
        raise OutputInvalidError(f"model output did not match the schema: {exc.errors()}") from exc


def _with_repair_note(request: Request, problem: str) -> Request:
    """Tell the model what was wrong, without letting its own output steer it.

    The problem is cut to a length ``pricing.REPAIR_NOTE_TOKENS`` covers.
    """
    note = (
        "\n\nYour previous reply could not be used. "
        f"{templates.fence('validation_error', problem[:_REPAIR_PROBLEM_CHARS])}\n"
        "Reply again with only a JSON object matching the schema. No prose, no code fence."
    )
    return Request(
        api_key=request.api_key,
        model=request.model,
        base_url=request.base_url,
        system=request.system,
        user=request.user + note,
        max_output_tokens=request.max_output_tokens,
    )
