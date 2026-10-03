"""Gap plans against a real database, with the model stubbed.

What is worth proving: a pasted JD is read, scored and planned for in one job;
the gaps come ranked by what they are worth, not by the model; a plan is kept
per version with finished work carried forward; a draft that invents evidence
or skips a gap is recorded as failed rather than stored; and nobody else can
read the plan.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio

from advisor.assessment import AssessmentService, create_assessment_service
from advisor.gapplan import GapPlanService, PlanStatus, create_gapplan_service
from advisor.identity import create_identity_service
from advisor.market import MarketService, create_market_service
from advisor.profile import create_profile_service
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
RELIABILITY = "Own reliability: SLOs and incident reviews"
ORG = "Demonstrated org-level influence"
# The profile holds one piece of evidence, so the prompt shows it as E1.
CITED = "E1"


class StubProvider(Provider):
    """Returns whatever the test queued, and records what it was asked."""

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


@dataclass
class World:
    stub: StubProvider
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    target: TargetService
    gapplan: GapPlanService
    evidence_id: str


@pytest_asyncio.fixture
async def world(
    database: Database,
    settings: Settings,
    account: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
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
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )
    evidence = await profile.record_answer(
        account,
        question_id="q1",
        question="Who led the checkout migration?",
        answer="I led it across two teams",
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    market = create_market_service(database, windows=WINDOWS)
    # A market of its own keeps the platform baseline out of this user's scope.
    await store_target_locations(database, account, [f"Plan market {uuid.uuid4().hex[:8]}"])
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
    gapplan = create_gapplan_service(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        rolemap=rolemap,
        gateway=gateway,
    )

    stub.replies.append(
        json.dumps(
            {
                "dimensions": [
                    {
                        "id": key,
                        "name": name,
                        "short_name": name,
                        "score": 70,
                        "confidence": 0.9,
                        "read": f"{name}, read from the evidence.",
                        "evidence_ids": [CITED],
                    }
                    for key, name in [
                        ("leadership", "Technical leadership"),
                        ("reliability", "Reliability"),
                        ("craft", "Backend craft"),
                        ("delivery", "Delivery"),
                        ("mentoring", "Mentoring"),
                    ]
                ]
            }
        )
    )
    await assessment.run(account)
    return World(
        stub=stub,
        market=market,
        rolemap=rolemap,
        assessment=assessment,
        target=target,
        gapplan=gapplan,
        evidence_id=str(evidence.id),
    )


def _score_the_jd(stub: StubProvider) -> None:
    """What reading a posting of the user's own answers: its requirements,
    then the fit projection."""
    stub.replies.append(
        json.dumps(
            {
                "name": "Whatever the model calls it",
                "requirements": [
                    {"statement": LEADS, "weight": 1.0, "expected_level": "expert"},
                    {"statement": RELIABILITY, "weight": 0.8, "expected_level": "advanced"},
                    {"statement": ORG, "weight": 0.5, "expected_level": "advanced"},
                ],
            }
        )
    )
    stub.replies.append(
        json.dumps(
            {
                "mappings": [
                    {"requirement_statement": LEADS, "dimension_id": "leadership"},
                    {"requirement_statement": RELIABILITY, "dimension_id": "reliability"},
                    {"requirement_statement": ORG, "dimension_id": None},
                ],
                "target_scores": [
                    {"dimension_id": "leadership", "target": 90},
                    {"dimension_id": "reliability", "target": 60},
                ],
                "reasoning": "Org influence has no evidence behind it at all.",
            }
        )
    )


async def _own_posting(
    world: World,
    account: uuid.UUID,
    *,
    title: str = "Staff Platform Engineer",
    company: str = "Meridian Labs",
) -> TargetRef:
    """A posting of the user's own, read and scored when it is set as the
    target (ADR 0034), aimed at as a Target (Phase 8)."""
    posting = await world.target.add_own_posting(
        account,
        title=title,
        company_name=company,
        requirements=("Set technical direction across three product teams...",),
    )
    _posting, run_id = await world.target.set_as_target(account, posting.private_job_posting_id)
    assert run_id is not None
    _score_the_jd(world.stub)
    await world.target.evaluate_own_posting(account, run_id)
    return TargetRef(private_job_posting_id=str(posting.private_job_posting_id))


async def test_a_posting_uploaded_as_a_file_is_read_scored_and_planned_for(
    world: World, account: uuid.UUID
) -> None:
    """The file goes to object storage, the worker reads it into the JD, and
    from there it is a posting of the user's own like one filled in."""
    posting = await world.target.upload_own_posting(
        account,
        title="Staff Platform Engineer",
        company_name="Meridian Labs",
        filename="meridian.txt",
        content_type="text/plain",
        content=b"Set technical direction across three product teams...",
    )
    assert (posting.source, posting.filename, posting.status) == (
        "uploaded",
        "meridian.txt",
        None,
    )
    _posting, run_id = await world.target.set_as_target(account, posting.private_job_posting_id)
    assert run_id is not None
    _score_the_jd(world.stub)

    await world.target.evaluate_own_posting(account, run_id)

    [listed] = await world.target.own_postings(account)
    assert listed.status == "ready", listed.error_message
    assert "Set technical direction" in world.stub.calls[-2].user
    ref = TargetRef(private_job_posting_id=str(posting.private_job_posting_id))
    world.stub.replies.append(_plan_reply(CITED))
    requested = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, requested.id)
    plan = await world.gapplan.get(account, requested.id)
    assert plan.summary.status is PlanStatus.READY, plan.summary.error_message
    assert [g.key for g in plan.gaps] == [ORG_KEY, LEAD_KEY]
    await world.target.remove_own_posting(account, posting.private_job_posting_id)


ORG_KEY = "req:demonstrated-org-level-influence"
LEAD_KEY = "dim:leadership"


def _plan_reply(cited: str, *, first_task: str = "Lead the checkout migration epic") -> str:
    return json.dumps(
        {
            "gaps": [
                {"key": ORG_KEY, "why": "They ask for it; nothing shows it.", "evidence_ids": []},
                {
                    "key": LEAD_KEY,
                    "why": "They expect 90; your leadership reads at 70.",
                    "evidence_ids": [cited],
                },
            ],
            "milestones": [
                {
                    "title": "Own one cross-team outcome",
                    "window": "Weeks 1-6",
                    "outcome": "The leadership artefact every panel asks for.",
                    "tasks": [
                        {"text": first_task, "due": "Wk 1", "closes": [LEAD_KEY]},
                        {"text": "Write the migration RFC", "due": "Wk 3", "closes": [LEAD_KEY]},
                    ],
                },
                {
                    "title": "Make the work visible",
                    "window": "Weeks 6-12",
                    "outcome": "Panels can only score what they can find.",
                    "tasks": [
                        {"text": "Present at all-hands", "due": "Wk 8", "closes": [ORG_KEY]},
                        {"text": "Run a guild on incidents", "due": "Wk 10", "closes": [ORG_KEY]},
                    ],
                },
            ],
            "projects": [
                {"name": "Public job runner", "note": "Evidence of design.", "closes": [LEAD_KEY]}
            ],
        }
    )


async def test_a_posting_of_your_own_is_planned_for_with_gaps_ranked_by_worth(
    world: World, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_plan_reply(CITED))
    calls_before = len(world.stub.calls)

    requested = await world.gapplan.request(account, ref)
    assert requested.status is PlanStatus.DRAFTING
    await world.gapplan.draft(account, requested.id)

    plan = await world.gapplan.get(account, requested.id)
    assert plan.summary.status is PlanStatus.READY, plan.summary.error_message
    assert plan.summary.label == "Staff Platform Engineer · Meridian Labs"
    # Denominator 90 + 60 + 50 = 200: no evidence for org influence is worth
    # 25 points, leadership's 20-point shortfall 10. Reliability is cleared.
    assert [(g.key, g.kind, g.lift) for g in plan.gaps] == [
        (ORG_KEY, "uncovered", 25),
        (LEAD_KEY, "dimension", 10),
    ]
    lead = plan.gaps[1]
    assert (lead.user_score, lead.target_score) == (70, 90)
    assert [e.id for e in lead.evidence] == [world.evidence_id]
    assert "I led it across two teams" in lead.evidence[0].fact

    assert plan.snapshot is not None
    assert plan.snapshot.basis == "posting"
    assert [m.title for m in plan.milestones] == [
        "Own one cross-team outcome",
        "Make the work visible",
    ]
    assert plan.summary.progress == 0
    assert plan.summary.model_id == "claude-opus-5"
    assert plan.template_version == "gap_plan@v1"
    # Only the draft runs on the key: the build already read the JD and
    # scored the role (ADR 0022).
    assert len(world.stub.calls) == calls_before + 1


async def test_regenerating_keeps_the_history_and_carries_finished_work(
    world: World, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_plan_reply(CITED))
    first = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, first.id)
    drafted = await world.gapplan.get(account, first.id)
    await world.gapplan.set_task_done(account, drafted.milestones[0].tasks[0].id, True)

    # The JD is already scored against this analysis: only the plan is drafted.
    calls_before = len(world.stub.calls)
    world.stub.replies.append(
        _plan_reply(CITED, first_task="Lead the checkout migration epic end to end")
    )
    second = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, second.id)
    assert len(world.stub.calls) == calls_before + 1

    regenerated = await world.gapplan.get(account, second.id)
    assert regenerated.summary.version == 2
    first_task = regenerated.milestones[0].tasks[0]
    assert first_task.done, "a reworded task closing the same gap stays finished"
    assert not regenerated.milestones[0].tasks[1].done
    assert regenerated.summary.progress == 25
    assert [v.version for v in regenerated.versions] == [2, 1]

    history = (await world.gapplan.history(account)).items
    assert [(p.id, p.version) for p in history] == [(second.id, 2)]


async def test_a_plan_citing_evidence_the_user_lacks_is_recorded_as_failed(
    world: World, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_plan_reply("E9"))

    requested = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, requested.id)

    plan = await world.gapplan.get(account, requested.id)
    assert plan.summary.status is PlanStatus.FAILED
    assert plan.summary.error_code == "evidence_not_owned"
    assert plan.milestones == ()


async def test_a_plan_that_leaves_a_gap_unexplained_is_rejected(
    world: World, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    reply = json.loads(_plan_reply(CITED))
    reply["gaps"] = reply["gaps"][1:]
    world.stub.replies.append(json.dumps(reply))

    requested = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, requested.id)

    plan = await world.gapplan.get(account, requested.id)
    assert plan.summary.status is PlanStatus.FAILED
    assert plan.summary.error_code == "plan_invalid"
    assert "unexplained" in (plan.summary.error_message or "")


async def test_another_user_cannot_read_the_plan(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_plan_reply(CITED))
    requested = await world.gapplan.request(account, ref)
    await world.gapplan.draft(account, requested.id)

    with pytest.raises(NotFoundError):
        await world.gapplan.get(other_account, requested.id)
    assert (await world.gapplan.history(other_account)).items == ()
