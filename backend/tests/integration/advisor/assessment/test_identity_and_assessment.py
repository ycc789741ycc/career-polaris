"""The path a user actually walks, against a real database.

The AI provider is stubbed — the point is the storage, the ownership checks and
the ledger, not the model.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from advisor.identity import IdentityService, create_identity_service
from advisor.profile import ProfileService, create_profile_service
from advisor.rolemap import create_rolemap_service
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway.providers import REGISTRY, Completion, Provider, Request
from kernel.config import Settings
from kernel.db import Database
from tests.integration.places import WINDOWS, store_target_locations

pytestmark = pytest.mark.integration


async def _recorded_build(database: Database, owner_id: uuid.UUID) -> uuid.UUID:
    """A build row for a recluster to be the work of, as ``request_build``
    records one: what each build made of the candidates hangs off it."""
    from advisor.rolemap.domain import BuildRun
    from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
    from kernel.clock import utcnow

    async with SqlAlchemyRoleMapUnitOfWork(database).for_owner(owner_id) as mine:
        build = await mine.builds.create(
            BuildRun.requested(owner_id=owner_id, at=utcnow(), wait=False)
        )
    return build.id


class StubProvider(Provider):
    """Stands in for a real model. Returns whatever the test queued.

    It replaces the *anthropic* registry entry rather than adding a new one, so
    the credential still goes through the same provider validation a real user
    would hit — a made-up provider name is correctly refused.
    """

    name = "anthropic"
    default_base_url = "https://llm.example.test"

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.calls: list[Request] = []

    async def complete(self, client: object, request: Request) -> Completion:
        self.calls.append(request)
        return Completion(
            text=self.replies.pop(0) if self.replies else "{}",
            input_tokens=1000,
            output_tokens=500,
            model=request.model,
        )

    async def stream(self, client: object, request: Request) -> AsyncIterator[str]:
        yield ""


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> StubProvider:
    provider = StubProvider()
    monkeypatch.setitem(REGISTRY, "anthropic", provider)
    return provider


Crawl = Callable[[list[tuple[str, str, str]]], Awaitable[str]]


@pytest_asyncio.fixture
async def crawled(crawler_database: Database) -> AsyncIterator[Crawl]:
    """Crawl postings into a place of their own, and return that place for a
    user to choose as their only target location. The postings go through the
    crawler role, as real ones do; a role map groups nothing else (ADR 0021)."""
    from advisor.market import NormalizedPosting, SourceKind, create_crawl_ingest
    from advisor.market.infra.models import CrawlSource

    sources: list[uuid.UUID] = []

    async def crawl(postings: list[tuple[str, str, str]]) -> str:
        place = f"Testplace{uuid.uuid4().hex[:10]}"
        async with crawler_database.shared() as session:
            row = CrawlSource(kind="greenhouse", endpoint=f"https://boards.test/{uuid.uuid4()}")
            session.add(row)
            await session.flush()
            sources.append(row.id)
        await create_crawl_ingest(crawler_database).record_crawl(
            sources[-1],
            [
                NormalizedPosting(
                    external_id=f"{company}-{title}",
                    company_name=company,
                    title=title,
                    location=place,
                    description=description,
                    url=f"https://boards.test/{uuid.uuid4().hex}",
                    source_kind=SourceKind.ATS_BOARD,
                    posted_on=date(2026, 9, 1),
                    salary=None,
                )
                for company, title, description in postings
            ],
        )
        return place

    yield crawl
    async with crawler_database.shared() as session:
        for source_id in sources:
            await session.execute(
                text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
            )


@pytest.fixture
def identity(database: Database) -> IdentityService:
    return create_identity_service(database, default_monthly_cap_usd=Decimal("20"))


# -- the credential ---------------------------------------------------------


async def test_the_stored_key_is_ciphertext_and_never_comes_back(
    database: Database, identity: IdentityService, account: uuid.UUID
) -> None:
    secret = "sk-ant-verysecretvalue1234"
    view = await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key=secret, base_url=None
    )

    assert view.last_four == "1234"
    read_back = await identity.credential(account)
    assert read_back is not None
    assert secret not in str(read_back)

    async with database.for_user(account) as session:
        stored = await session.execute(
            text(
                "SELECT encrypted_api_key FROM identity.provider_credential WHERE owner_id = :owner"
            ),
            {"owner": account},
        )
        ciphertext = stored.scalar_one()
    assert secret not in ciphertext


async def test_one_user_cannot_load_anothers_credential(
    identity: IdentityService, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    from kernel.errors import CredentialMissingError

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-mine", base_url=None
    )
    with pytest.raises(CredentialMissingError):
        await identity.load(other_account)


async def test_a_self_hosted_model_on_a_private_address_is_refused(
    identity: IdentityService, account: uuid.UUID
) -> None:
    """'Local' means a public URL the user controls, not our own network."""
    from kernel.errors import BlockedAddressError

    with pytest.raises(BlockedAddressError):
        await identity.set_credential(
            account,
            provider="local",
            model="llama",
            api_key="k",
            base_url="http://169.254.169.254/v1",
        )


# -- budget and ledger ------------------------------------------------------


async def test_every_call_lands_in_the_ledger_and_moves_the_budget(
    database: Database,
    identity: IdentityService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)

    from pydantic import BaseModel

    class Answer(BaseModel):
        ok: bool

    from kernel.ai_gateway.templates import PromptTemplate

    stub_provider.replies.append('{"ok": true}')
    await gateway.run(
        account,
        task="test.task",
        template=PromptTemplate("t", "v1", "sys", "do {{thing}}", 100),
        inputs={"thing": "something"},
        output_schema=Answer,
    )

    budget = await identity.budget(account)
    assert budget.spent_this_month_usd > 0
    assert budget.remaining_usd < budget.monthly_cap_usd

    async with database.for_user(account) as session:
        rows = await session.execute(
            text(
                "SELECT task, model, input_tokens, output_tokens "
                "FROM identity.ai_usage_ledger WHERE owner_id = :owner"
            ),
            {"owner": account},
        )
        entry = rows.one()
    assert entry.task == "test.task"
    assert (entry.input_tokens, entry.output_tokens) == (1000, 500)


async def test_a_call_past_the_cap_pauses_the_user_instead_of_running(
    database: Database,
    identity: IdentityService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    from kernel.errors import BudgetExceededError

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    await identity.set_budget(account, monthly_cap_usd=Decimal("0.000001"))
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)

    from pydantic import BaseModel

    from kernel.ai_gateway.templates import PromptTemplate

    class Answer(BaseModel):
        ok: bool

    with pytest.raises(BudgetExceededError):
        await gateway.run(
            account,
            task="test.task",
            template=PromptTemplate("t", "v1", "sys", "do {{thing}}", 100),
            inputs={"thing": "x"},
            output_schema=Answer,
        )

    assert stub_provider.calls == [], "no money may be spent past the cap"
    assert (await identity.account(account)).background_jobs_paused


# -- evidence and the assessment -------------------------------------------


@pytest.fixture
def profile(database: Database, settings: Settings) -> ProfileService:
    from kernel.storage import ObjectStore

    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def test_an_answer_becomes_evidence_and_bumps_the_profile_version(
    profile: ProfileService, account: uuid.UUID
) -> None:
    before = await profile.snapshot(account)
    await profile.record_answer(
        account,
        question_id="q1",
        question="Did you design the failover or execute it?",
        answer="I designed it",
    )
    after = await profile.snapshot(account)

    assert after.version == before.version + 1
    assert any("I designed it" in item.fact for item in after.evidence)
    assert any(item.source == "user_answer" for item in after.evidence)


async def test_an_assessment_citing_evidence_the_user_lacks_is_rejected(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    """The guard against invented claims, end to end."""
    from advisor.assessment import create_assessment_service
    from advisor.market import create_market_service
    from kernel.errors import EvidenceNotOwnedError

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    await profile.record_answer(
        account, question_id="q1", question="Anything?", answer="Yes, plenty."
    )

    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    market = create_market_service(database, windows=WINDOWS)
    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
        top_k=settings.role_map_top_k,
        candidate_count=settings.role_candidate_count,
    )
    assessment = create_assessment_service(
        database,
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
        candidate_count=settings.role_candidate_count,
    )

    dimensions = [
        {
            "id": f"d{i}",
            "name": f"Dimension {i}",
            "short_name": f"D{i}",
            "score": 70,
            "confidence": 0.9,
            "read": "A read.",
            # An id that belongs to nobody.
            "evidence_ids": ["00000000-0000-0000-0000-000000000000"],
        }
        for i in range(5)
    ]
    import json

    stub_provider.replies.append(json.dumps({"dimensions": dimensions}))

    with pytest.raises(EvidenceNotOwnedError, match="not in your profile"):
        await assessment.run(account)


# -- the role map -----------------------------------------------------------


async def test_the_role_map_estimate_runs_no_local_ml(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    crawled: Crawl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The api prices a role map without embeddings — it has no model cache,
    and a read-only filesystem to put one on."""
    import advisor.rolemap.service as rolemap_service
    from advisor.market import create_market_service

    def no_local_ml(*args: object, **kwargs: object) -> None:
        raise AssertionError("the cost estimate must not embed")

    monkeypatch.setattr(rolemap_service, "embed", no_local_ml)

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    market = create_market_service(database, windows=WINDOWS)
    place = await crawled(
        [
            (f"Company {i}", "Backend engineer", "Python, Postgres and queues. " * (i + 1))
            for i in range(7)
        ]
    )
    await store_target_locations(database, account, [place])
    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=AiGateway(settings=settings, credentials=identity, budget=identity),
        embedding_model=settings.embedding_model_name,
        top_k=settings.role_map_top_k,
        candidate_count=settings.role_candidate_count,
    )

    estimate = await rolemap.estimate_cost(account)

    # Seven postings can be openings for at most two roles of three.
    assert estimate["max_roles"] == 2
    assert Decimal(estimate["cost_usd"]) > 0
    assert estimate["model_id"] == "claude-opus-5"


async def test_a_role_map_analyses_the_first_ten_candidates_the_market_has(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    crawled: Crawl,
    stub_provider: StubProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fourteen candidates, two of them absent from the market: the key is spent
    on the first ten the market has, in the analysis's order (ADR 0024)."""
    import json
    import re

    import advisor.rolemap.service as rolemap_service
    from advisor.market import create_market_service
    from advisor.rolemap import CandidateInput
    from kernel.embeddings import EMBEDDING_DIMENSIONS

    # A stand-in embedding: each "group-N" marker in a text adds weight on axis N.
    def fake_embed(texts: list[str], *, model_name: str) -> list[list[float]]:
        vectors = []
        for text_ in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            for marker in re.findall(r"group-(\d+)", text_):
                vector[int(marker)] += 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(rolemap_service, "embed", fake_embed)

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    market = create_market_service(database, windows=WINDOWS)
    place = await crawled(
        [
            (f"Company {group}-{copy}", f"Role group-{group}", "What the job involves.")
            for group in range(12)
            for copy in range(3)
        ]
    )
    await store_target_locations(database, account, [place])
    # Groups 12 and 13 have no openings; 0 to 11 do, and only ten are kept.
    order = [13, 12, *range(12)]
    # Set here rather than read from .env: fourteen candidates, ten kept.
    top_k, candidate_count = 10, 20

    for group in range(top_k):
        stub_provider.replies.append(
            json.dumps(
                {
                    "name": f"Role {group}",
                    "requirements": [
                        {"statement": "Python", "weight": 0.5, "expected_level": "senior"}
                    ],
                }
            )
        )
        stub_provider.replies.append(
            json.dumps({"difficulty": 50, "confidence": 0.5, "reasoning": "A guess."})
        )

    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=AiGateway(settings=settings, credentials=identity, budget=identity),
        embedding_model=settings.embedding_model_name,
        top_k=top_k,
        candidate_count=candidate_count,
    )
    await rolemap.replace_candidates(
        account,
        uuid.uuid4(),
        [
            CandidateInput(
                title=f"Candidate group-{group}",
                description=f"The group-{group} work.",
                dimension_keys=("backend",),
            )
            for group in order
        ],
    )
    roles = await rolemap.recluster(account, await _recorded_build(database, account))

    assert len(roles) == top_k
    assert len(stub_provider.calls) == 2 * top_k
    analysed = {
        match.group(1)
        for call in stub_provider.calls
        if (match := re.search(r"group-(\d+)", call.user)) is not None
    }
    assert analysed == {str(g) for g in range(10)}

    candidates = await rolemap.candidates(account)
    placed = {c.title.removeprefix("Candidate ") for c in candidates if c.role_id is not None}
    assert placed == {f"group-{g}" for g in range(10)}
    assert [c.opening_count for c in candidates[:2]] == [0, 0]

    # The same market again: the roles are kept and nothing is spent.
    again = await rolemap.recluster(account, await _recorded_build(database, account))
    assert {r.id for r in again} == {r.id for r in roles}
    assert len(stub_provider.calls) == 2 * top_k


async def test_an_analysis_stores_the_roles_it_recommends_for_the_role_map(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    """Assessment writes the candidates rolemap owns, in the user's own scope."""
    import json

    from advisor.assessment import create_assessment_service
    from advisor.market import create_market_service

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    await profile.record_answer(
        account, question_id="q1", question="Anything?", answer="Yes, plenty."
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    market = create_market_service(database, windows=WINDOWS)
    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
        top_k=settings.role_map_top_k,
        candidate_count=settings.role_candidate_count,
    )
    assessment = create_assessment_service(
        database,
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
        candidate_count=settings.role_candidate_count,
    )
    stub_provider.replies.append(
        json.dumps(
            {
                "dimensions": [
                    {
                        "id": f"d{i}",
                        "name": f"Dimension {i}",
                        "short_name": f"D{i}",
                        "score": 70,
                        "confidence": 0.9,
                        "read": "A read.",
                        "evidence_ids": ["E1"],
                    }
                    for i in range(5)
                ],
                "candidates": [
                    {
                        "title": "Platform Engineer",
                        "description": "Runs the platform.",
                        "dimension_ids": ["d0", "d3"],
                    }
                ],
            }
        )
    )

    stored = await assessment.run(account)

    [candidate] = await rolemap.candidates(account)
    assert (candidate.title, candidate.dimension_keys) == ("Platform Engineer", ("d0", "d3"))
    assert candidate.role_id is None
    async with database.for_user(account) as session:
        recorded = await session.execute(
            text("SELECT assessment_id FROM rolemap.role_candidate WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert recorded.scalar_one() == stored.id


# -- ten roles, fixed (ADR 0020) ---------------------------------------------


async def test_a_small_k_names_analyses_and_scores_only_k_roles(
    database: Database,
    identity: IdentityService,
    settings: Settings,
    account: uuid.UUID,
    crawled: Crawl,
    stub_provider: StubProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five candidates on the market and k = 3: three roles are named and
    analysed, three fits scored, and the other two are kept unplaced with their
    openings counted. Nothing is sent to the model for them (ADR 0029)."""
    import json
    import re

    import advisor.rolemap.service as rolemap_service
    from advisor.market import create_market_service
    from advisor.rolemap import CandidateInput, StrengthInput
    from kernel.embeddings import EMBEDDING_DIMENSIONS

    def fake_embed(texts: list[str], *, model_name: str) -> list[list[float]]:
        vectors = []
        for text_ in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            for marker in re.findall(r"group-(\d+)", text_):
                vector[int(marker)] += 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(rolemap_service, "embed", fake_embed)
    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    market = create_market_service(database, windows=WINDOWS)
    place = await crawled(
        [
            (f"Company {group}-{copy}", f"Role group-{group}", "What the job involves.")
            for group in range(5)
            for copy in range(3)
        ]
    )
    await store_target_locations(database, account, [place])
    for group in range(3):
        stub_provider.replies.append(
            json.dumps(
                {
                    "name": f"Role {group}",
                    "requirements": [
                        {"statement": "Python", "weight": 0.5, "expected_level": "senior"}
                    ],
                }
            )
        )
        stub_provider.replies.append(
            json.dumps({"difficulty": 50, "confidence": 0.5, "reasoning": "A guess."})
        )
    for _ in range(3):
        stub_provider.replies.append(
            json.dumps(
                {
                    "mappings": [{"requirement_statement": "Python", "dimension_id": "backend"}],
                    "target_scores": [{"dimension_id": "backend", "target": 80}],
                    "reasoning": "Close.",
                }
            )
        )

    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=AiGateway(settings=settings, credentials=identity, budget=identity),
        embedding_model=settings.embedding_model_name,
        top_k=3,
        candidate_count=5,
    )
    await rolemap.replace_candidates(
        account,
        uuid.uuid4(),
        [
            CandidateInput(
                title=f"Candidate group-{group}",
                description=f"The group-{group} work.",
                dimension_keys=("backend",),
            )
            for group in range(5)
        ],
        strengths=[StrengthInput("backend", "Backend", "Builds services.", 70, 0.8)],
    )

    roles = await rolemap.recluster(account, await _recorded_build(database, account))
    fits = await rolemap.compute_fits(account)

    assert len(roles) == 3
    assert len(fits) == 3
    # Two calls to name and read each kept role, one to score each fit.
    assert len(stub_provider.calls) == 3 * 3
    # Scored again with nothing changed: the same fits, and no call (Phase 8).
    assert await rolemap.compute_fits(account) == fits
    assert len(stub_provider.calls) == 3 * 3
    async with database.for_user(account) as session:
        stored = await session.execute(
            text("SELECT count(*) FROM rolemap.role_fit WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert stored.scalar_one() == 3
        # Every opening of the three roles has its own fit, worked out from
        # its role's with no call (Phase 8).
        openings = await session.execute(
            text(
                "SELECT count(*) FROM rolemap.posting_fit"
                " WHERE owner_id = :owner AND basis = 'role'"
            ),
            {"owner": account},
        )
        assert openings.scalar_one() == 9
    [first, *_] = roles
    ranked = await rolemap.matched_postings(account, limit=None, role_id=first.id)
    assert len(ranked) == 3 and {m.fit_basis for m in ranked} == {"posting"}
    candidates = await rolemap.candidates(account)
    assert sum(1 for c in candidates if c.role_id is not None) == 3
    assert [c.opening_count for c in candidates if c.role_id is None] == [3, 3]
    estimate = await rolemap.estimate_cost(account)
    assert estimate["max_roles"] == 3


async def test_the_ceiling_is_k_roles_however_large_the_market(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    crawled: Crawl,
) -> None:
    from advisor.market import create_market_service

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    market = create_market_service(database, windows=WINDOWS)
    place = await crawled(
        [(f"Company {i}", "Backend engineer", "Python, Postgres and queues.") for i in range(60)]
    )
    await store_target_locations(database, account, [place])
    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=AiGateway(settings=settings, credentials=identity, budget=identity),
        embedding_model=settings.embedding_model_name,
        top_k=settings.role_map_top_k,
        candidate_count=settings.role_candidate_count,
    )

    estimate = await rolemap.estimate_cost(account)

    assert estimate["max_roles"] == settings.role_map_top_k
    assert "role_count" not in estimate
