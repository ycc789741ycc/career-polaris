"""Fill the gap against a real database, with the model stubbed (ADR 0023).

What is worth proving: questions are written for a Target's gaps and stored
with them; one submit turns the answers into ``user_answer`` evidence, links
each question to it and tells the dispatcher, in the outbox, which Target to
regenerate; and nobody else can read the questions.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from advisor.assessment import AssessmentService, create_assessment_service
from advisor.gapfill import Answer, GapFillService, create_gapfill_service
from advisor.identity import create_identity_service
from advisor.market import MarketService, create_market_service
from advisor.profile import EvidenceSource, ProfileService, create_profile_service
from advisor.rolemap import RoleMapService, create_rolemap_service
from advisor.target import TargetRef, TargetService, create_target_service
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway.providers import REGISTRY, Completion, Provider, Request
from kernel.config import Settings
from kernel.db import Database
from kernel.errors import NotFoundError
from kernel.storage import ObjectStore
from tests.integration.places import WINDOWS, store_target_locations

pytestmark = pytest.mark.integration

LEADS = "Lead technical direction across several teams"
ORG = "Demonstrated org-level influence"
ORG_KEY = "req:demonstrated-org-level-influence"


class StubProvider(Provider):
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
        # A job's call streams (ADR 0042): the queued reply, in one chunk.
        self.calls.append(request)
        yield self.replies.pop(0) if self.replies else "{}"


@dataclass
class World:
    stub: StubProvider
    market: MarketService
    profile: ProfileService
    rolemap: RoleMapService
    assessment: AssessmentService
    target: TargetService
    gapfill: GapFillService


@pytest_asyncio.fixture
async def world(
    database: Database, settings: Settings, account: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> World:
    stub = StubProvider()
    monkeypatch.setitem(REGISTRY, "anthropic", stub)
    identity = create_identity_service(database, default_monthly_cap_usd=Decimal("20"))
    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    profile = create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={},
        token_refreshers={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )
    await profile.record_answer(
        account, question_id="seed", question="Who led the migration?", answer="I did"
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    market = create_market_service(database, windows=WINDOWS)
    # A place of its own keeps the platform baseline out of this user's scope.
    await store_target_locations(database, account, [f"Fill market {uuid.uuid4().hex[:8]}"])
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
    target = create_target_service(
        database,
        assessment=assessment,
        rolemap=rolemap,
        object_store=ObjectStore(settings),
        upload_max_bytes=settings.own_posting_max_bytes,
        upload_max_pages=settings.own_posting_max_pages,
    )
    gapfill = create_gapfill_service(database, target=target, profile=profile, gateway=gateway)
    stub.replies.append(
        json.dumps(
            {
                "dimensions": [
                    {
                        "id": key,
                        "name": key.title(),
                        "short_name": key.title(),
                        "score": 70,
                        "confidence": 0.9,
                        "read": "Read from the evidence.",
                        "evidence_ids": ["E1"],
                    }
                    for key in ("leadership", "reliability", "craft", "delivery", "mentoring")
                ]
            }
        )
    )
    await assessment.run(account)
    return World(stub, market, profile, rolemap, assessment, target, gapfill)


async def _own_posting(world: World, account: uuid.UUID) -> TargetRef:
    """A posting of the user's own, read and scored when it is set as the
    target (ADR 0034)."""
    posting = await world.target.add_own_posting(
        account,
        title="Staff Platform Engineer",
        company_name="Meridian Labs",
        requirements=("Set technical direction across three product teams...",),
    )
    _posting, run_id = await world.target.set_as_target(account, posting.private_job_posting_id)
    assert run_id is not None
    world.stub.replies += [
        json.dumps(
            {
                "name": "Staff Platform Engineer",
                "requirements": [
                    {"statement": LEADS, "weight": 1.0, "expected_level": "expert"},
                    {"statement": ORG, "weight": 0.5, "expected_level": "advanced"},
                ],
            }
        ),
        json.dumps(
            {
                "mappings": [
                    {"requirement_statement": LEADS, "dimension_id": "leadership"},
                    {"requirement_statement": ORG, "dimension_id": None},
                ],
                "target_scores": [{"dimension_id": "leadership", "target": 90}],
                "reasoning": "Org influence has no evidence behind it.",
            }
        ),
    ]
    await world.target.evaluate_own_posting(account, run_id)
    return TargetRef(private_job_posting_id=str(posting.private_job_posting_id))


def _questions() -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "gap_key": ORG_KEY,
                    "text": "Did another team build on a design you wrote?",
                    "asked_because": "Nothing in your sources speaks to influence beyond a team.",
                    "answer_type": "both",
                    "choices": ["Yes", "Not yet"],
                },
                {
                    "gap_key": "dim:leadership",
                    "text": "How many engineers did your largest design touch?",
                    "asked_because": "Leadership reads from one RFC.",
                    "answer_type": "choice",
                    "choices": ["1 to 3", "4 to 10", "More than 10"],
                },
            ]
        }
    )


async def test_questions_are_written_for_the_gaps_and_answers_become_evidence(
    world: World, database: Database, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_questions())

    requested = await world.gapfill.request(account, ref)
    await world.gapfill.write(account, requested.id)
    written = await world.gapfill.get(account, requested.id)

    assert written.status == "ready", written.error_message
    assert [g.key for g in written.gaps] == [ORG_KEY, "dim:leadership"]
    org, lead = written.questions
    assert org.gap_key == ORG_KEY and org.answer_type == "both"

    done = await world.gapfill.submit(
        account,
        written.id,
        [
            Answer(question_id=org.id, choice="Yes", text="Payments built on my ledger RFC."),
            Answer(question_id=lead.id, choice="4 to 10"),
        ],
    )

    assert len(done.evidence_ids) == 2 and done.skipped == 0
    snapshot = await world.profile.snapshot(account)
    answers = [e for e in snapshot.evidence if e.id in done.evidence_ids]
    assert {e.source for e in answers} == {EvidenceSource.USER_ANSWER}
    assert any("Payments built on my ledger RFC." in e.fact for e in answers)
    after = await world.gapfill.get(account, written.id)
    assert after.submitted_at is not None
    assert {q.evidence_id for q in after.questions} == set(done.evidence_ids)

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT payload FROM outbox.event "
                "WHERE owner_id = :owner AND name = 'GapAnswersSubmitted'"
            ),
            {"owner": account},
        )
        [payload] = rows.scalars().all()
    assert payload["private_job_posting_id"] == ref.private_job_posting_id
    assert payload["role_id"] is None and payload["job_posting_id"] is None
    assert sorted(payload["evidence_ids"]) == sorted(str(e) for e in done.evidence_ids)


async def test_another_user_cannot_read_the_questions(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    requested = await world.gapfill.request(account, ref)

    with pytest.raises(NotFoundError):
        await world.gapfill.get(other_account, requested.id)
    assert await world.gapfill.current(other_account, ref) is None
