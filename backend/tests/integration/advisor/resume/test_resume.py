"""The Resume Advisor against a real database and object store, model stubbed.

What is worth proving: a résumé is written for a Target with every written line
cited and its requirement coverage decided by scores; invented evidence fails
the draft; a user's edit is theirs but cannot cite someone else's evidence; the
chat streams a proposal that becomes a version only when applied; an export is
a real PDF in object storage behind a signed link; and nobody else can read it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from advisor.assessment import AssessmentService, create_assessment_service
from advisor.gapfill import Answer, GapFillService, create_gapfill_service
from advisor.identity import create_identity_service
from advisor.market import MarketService, create_market_service
from advisor.profile import ProfileService, create_profile_service
from advisor.resume import (
    Options,
    ResumeService,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    SectionKind,
    SectionSlot,
    Template,
    create_resume_service,
)
from advisor.resume.domain import Layout, TemplateSpec
from advisor.rolemap import RoleMapService, create_rolemap_service
from advisor.target import TargetRef, TargetService, create_target_service
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway.providers import REGISTRY, Completion, Provider, Request
from kernel.config import Settings
from kernel.db import Database
from kernel.errors import EvidenceNotOwnedError, NotFoundError
from kernel.storage import ObjectStore
from tests.integration.places import WINDOWS, store_target_locations

pytestmark = pytest.mark.integration

LEADS = "Lead technical direction across several teams"
RELIABILITY = "Own reliability: SLOs and incident reviews"
ORG = "Demonstrated org-level influence"
ORG_KEY = "req:demonstrated-org-level-influence"
# The profile holds one piece of evidence, so the prompt shows it as E1.
CITED = "E1"


class StubProvider(Provider):
    """Completions and streams, each from what the test queued."""

    name = "anthropic"
    default_base_url = "https://llm.example.test"

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.streams: list[list[str]] = []
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
        self.calls.append(request)
        if "<<<PROPOSAL>>>" not in request.system + request.user:
            # A job's call streams too (ADR 0042): the queued reply, whole.
            yield self.replies.pop(0) if self.replies else "{}"
            return
        for chunk in self.streams.pop(0) if self.streams else []:
            yield chunk


@dataclass
class World:
    stub: StubProvider
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    target: TargetService
    resume: ResumeService
    store: ObjectStore
    evidence_id: str
    profile: ProfileService
    gapfill: GapFillService


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
    store = ObjectStore(settings)
    profile = create_profile_service(
        database,
        object_store=store,
        connectors={},
        token_refreshers={},
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
    await store_target_locations(database, account, [f"Résumé market {uuid.uuid4().hex[:8]}"])
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
        object_store=store,
        upload_max_bytes=settings.own_posting_max_bytes,
        upload_max_pages=settings.own_posting_max_pages,
    )
    gapfill = create_gapfill_service(database, target=target, profile=profile, gateway=gateway)
    resume = create_resume_service(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        gapfill=gapfill,
        gateway=gateway,
        object_store=store,
        template_max=settings.resume_template_max,
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
        resume=resume,
        store=store,
        evidence_id=str(evidence.id),
        profile=profile,
        gapfill=gapfill,
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


def _resume_reply(cited: str) -> str:
    return json.dumps(
        {
            "name": "Maya Lin Chen",
            "headline": "Staff Platform Engineer",
            "contact": "maya@example.com",
            "sections": [
                {"kind": "summary", "text": "Leads platform work across teams."},
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "title": "Backend Engineer",
                            "org": "Kestrel Financial",
                            "when": "2022 — now",
                            "bullets": [
                                {
                                    "text": "Led the checkout migration across two teams",
                                    "evidence_ids": [cited],
                                    "answers": RELIABILITY,
                                }
                            ],
                        }
                    ],
                },
                {"kind": "skills", "items": ["Go", "Postgres"]},
            ],
        }
    )


def _lines(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The first experience entry's lines, in stored content."""
    experience = next(s for s in content["sections"] if s["kind"] == "experience")
    lines: list[dict[str, Any]] = experience["entries"][0]["bullets"]
    return lines


def _summary(content: Any) -> str:
    return next(s.text for s in content.sections if str(s.kind) == "summary")


async def _written(world: World, account: uuid.UUID) -> uuid.UUID:
    ref = await _own_posting(world, account)
    world.stub.replies.append(_resume_reply(CITED))
    requested = await world.resume.request(
        account,
        ref,
        template=Template.ORGANIC,
        options=Options(),
    )
    await world.resume.generate(account, requested.id)
    return requested.id


async def test_a_resume_is_written_cited_with_coverage_decided_by_scores(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)

    view = await world.resume.get(account, resume_id)
    assert view.summary.status == "ready", view.summary.error_message
    assert view.version is not None
    assert (view.version.number, str(view.version.source)) == (1, "generated")
    assert view.content is not None
    [bullet] = _lines(view.content.to_dict())
    assert bullet["evidence_ids"] == [world.evidence_id]
    assert "I led it across two teams" in view.evidence[world.evidence_id].fact

    # 70 against 90 is 20 short: a gap. 70 against 60 clears it. Org influence
    # maps to nothing the user has, so there is nothing to cover it with.
    assert [(c.requirement, c.verdict) for c in view.coverage] == [
        (LEADS, "gap"),
        (RELIABILITY, "covered"),
        (ORG, "gap"),
    ]
    assert [e.id for e in view.coverage[1].evidence] == [world.evidence_id]


async def test_a_resume_citing_evidence_the_user_lacks_is_recorded_as_failed(
    world: World, account: uuid.UUID
) -> None:
    ref = await _own_posting(world, account, title="Engineer", company="Acme")
    world.stub.replies.append(_resume_reply("E9"))
    requested = await world.resume.request(
        account,
        ref,
        template=Template.PLAIN,
        options=Options(),
    )
    await world.resume.generate(account, requested.id)

    view = await world.resume.get(account, requested.id)
    assert view.summary.status == "failed"
    assert view.summary.error_code == "evidence_not_owned"
    assert view.versions == ()


async def test_an_edit_is_the_users_own_but_cannot_cite_someone_elses_evidence(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    edited = view.content.to_dict()
    _lines(edited)[0]["text"] = "Led checkout's migration, end to end"

    saved = await world.resume.save_version(account, resume_id, content=edited)
    assert (saved.number, str(saved.source)) == (2, "manual")
    again = await world.resume.get(account, resume_id)
    assert again.content is not None
    assert _lines(again.content.to_dict())[0]["origin"] == "yours"

    # Unchanged text is the same line: its stored citation stands, and an id
    # slipped in beside it is not what gets saved.
    stranger = str(uuid.uuid4())
    _lines(edited)[0]["evidence_ids"] = [stranger]
    await world.resume.save_version(account, resume_id, content=edited)
    kept = await world.resume.get(account, resume_id)
    assert kept.content is not None
    assert stranger not in kept.content.cited()

    # A line the user rewrites keeps what they cite — which must be theirs.
    _lines(edited)[0]["text"] = "Led the migration, start to finish"
    with pytest.raises(EvidenceNotOwnedError):
        await world.resume.save_version(account, resume_id, content=edited)


async def test_a_chat_proposal_streams_and_becomes_a_version_only_when_applied(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    current = view.content.to_dict()
    proposed = json.loads(_resume_reply(CITED))
    proposed["sections"][0]["text"] = "Short."
    world.stub.streams.append(
        [
            "Shorter summary; ",
            "the lead line stays.\n<<<PRO",
            "POSAL>>>",
            json.dumps({"changed": True, "resume": proposed}),
        ]
    )

    events = [
        event
        async for event in world.resume.revise(
            account, resume_id, request="Make the summary shorter", content=current
        )
    ]

    text = "".join(e.text for e in events if isinstance(e, RevisionText))
    assert text == "Shorter summary; the lead line stays.\n"
    done = events[-1]
    assert isinstance(done, RevisionDone)
    assert done.proposal is not None and _summary(done.proposal) == "Short."
    assert len((await world.resume.get(account, resume_id)).versions) == 1

    applied = await world.resume.apply_revision(account, resume_id, done.revision_id)
    assert (applied.number, str(applied.source)) == (2, "chat")
    after = await world.resume.get(account, resume_id)
    assert after.content is not None and _summary(after.content) == "Short."
    assert after.revisions[0].applied_version_id == applied.id


async def test_a_proposal_with_an_uncited_new_line_is_rejected_in_the_stream(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    proposed = json.loads(_resume_reply(CITED))
    _lines(proposed).append({"text": "Promoted to Staff in 2024", "evidence_ids": []})
    world.stub.streams.append(
        [
            "Added your promotion.",
            "<<<PROPOSAL>>>",
            json.dumps({"changed": True, "resume": proposed}),
        ]
    )

    events = [
        e
        async for e in world.resume.revise(
            account, resume_id, request="Add a promotion", content=view.content.to_dict()
        )
    ]

    assert isinstance(events[-1], RevisionFailed)
    assert events[-1].code == "ai_output_invalid"
    assert (await world.resume.get(account, resume_id)).revisions == ()


async def test_an_export_is_a_pdf_in_object_storage_behind_a_signed_link(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    export = await world.resume.request_export(account, resume_id, number=1)
    assert export.status == "rendering"

    await world.resume.export(account, export.id)

    ready = await world.resume.get_export(account, export.id)
    assert ready.status == "ready", ready.error_message
    assert ready.download_url is not None and "X-Amz-Signature" in ready.download_url
    # It downloads the file, under the person's name and the role (ADR 0038).
    disposition = parse_qs(urlparse(ready.download_url).query)["response-content-disposition"]
    assert disposition[0].startswith('attachment; filename="')
    assert disposition[0].endswith(".pdf")
    # Asked for again unchanged, the rendered file is reused.
    again = await world.resume.request_export(account, resume_id, number=1)
    assert (again.id, again.status) == (export.id, "ready")
    key = f"users/{account}/exports/{export.id}.pdf"
    try:
        assert world.store.get(key).startswith(b"%PDF-")
    finally:
        world.store.delete(key)


async def test_new_evidence_marks_the_resume_outdated_until_it_is_regenerated(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """Answering spends nothing: the résumé says it is outdated, and writing
    it again is a request, saved as its next version (ADR 0035)."""
    resume_id = await _written(world, account)
    assert (await world.resume.get(account, resume_id)).outdated_by == ()

    await world.profile.record_answer(
        account, question_id="later", question="Did another team adopt it?", answer="Yes"
    )
    outdated = await world.resume.get(account, resume_id)
    assert [str(r) for r in outdated.outdated_by] == ["evidence"]
    assert [v.number for v in outdated.versions] == [1]

    with pytest.raises(NotFoundError):
        await world.resume.redraft(other_account, resume_id)
    await world.resume.redraft(account, resume_id)
    world.stub.replies.append(_resume_reply(CITED))
    await world.resume.generate(account, resume_id)

    regenerated = await world.resume.get(account, resume_id)
    assert regenerated.summary.status == "ready", regenerated.summary.error_message
    assert [v.number for v in regenerated.versions] == [2, 1]
    assert regenerated.outdated_by == ()


async def test_a_section_is_added_filled_and_kept_when_the_resume_is_regenerated(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """Sections the user chose are the résumé's plan (ADR 0039)."""
    resume_id = await _written(world, account)
    education = SectionSlot(SectionKind.EDUCATION)
    with pytest.raises(NotFoundError):
        await world.resume.request_section(other_account, resume_id, education)

    filling = await world.resume.request_section(account, resume_id, education)
    assert filling.status == "filling"
    world.stub.replies.append(
        json.dumps(
            {
                "section": {
                    "kind": "education",
                    "entries": [
                        {
                            "title": "Led a study group",
                            "org": "TU Berlin",
                            "when": "2016",
                            "bullets": [
                                {"text": "Ran the systems study group", "evidence_ids": [CITED]}
                            ],
                        }
                    ],
                }
            }
        )
    )
    await world.resume.fill_section(account, resume_id, education)

    filled = await world.resume.get(account, resume_id)
    assert filled.summary.status == "ready", filled.summary.error_message
    assert filled.content is not None
    shown = [str(s.kind) for s in filled.content.sections if s.is_shown]
    assert shown == ["summary", "experience", "skills", "education"]
    assert next(s for s in filled.section_plan if s == education).is_shown
    plan = [(str(s.kind), s.is_shown) for s in filled.section_plan]

    await world.resume.redraft(account, resume_id)
    world.stub.replies.append(_resume_reply(CITED))
    await world.resume.generate(account, resume_id)

    again = await world.resume.get(account, resume_id)
    assert again.content is not None
    # The reply wrote three sections; every other keeps its place and state,
    # education shown and empty.
    assert [(str(s.kind), s.is_shown) for s in again.content.sections] == plan
    refilled = again.content.get_section(education)
    assert refilled is not None and refilled.is_empty


async def test_another_user_cannot_read_the_resume_or_its_export(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    export = await world.resume.request_export(account, resume_id, number=1)

    with pytest.raises(NotFoundError):
        await world.resume.get(other_account, resume_id)
    with pytest.raises(NotFoundError):
        await world.resume.get_export(other_account, export.id)
    assert (await world.resume.saved(other_account)).items == ()


async def test_a_template_of_your_own_sets_the_pdf_and_is_yours_alone(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """ADR 0040: a checked spec, kept under row-level security, rendered by
    WeasyPrint in its layout; deleting it moves its résumés to Organic."""
    spec = {
        **TemplateSpec().to_dict(),
        "layout": "sidebar_left",
        "sidebar_kinds": ["skills"],
        "heading_font": "DejaVu Serif",
        "accent_color": "#2a6f97",
    }
    mine = await world.resume.create_template(account, name="Two columns", spec=spec)
    resume_id = await _written(world, account)
    await world.resume.update_settings(account, resume_id, template=mine.id, options=Options())

    export = await world.resume.request_export(account, resume_id, number=1)
    await world.resume.export(account, export.id)
    ready = await world.resume.get_export(account, export.id)
    key = f"users/{account}/exports/{export.id}.pdf"
    try:
        assert ready.status == "ready", ready.error_message
        assert ready.template is None
        assert world.store.get(key).startswith(b"%PDF-")
    finally:
        world.store.delete(key)

    assert [t.id for t in (await world.resume.templates(other_account)).items] == [
        "organic",
        "plain",
    ]
    with pytest.raises(NotFoundError):
        await world.resume.update_template(other_account, uuid.UUID(mine.id), name="x", spec=spec)

    await world.resume.delete_template(account, uuid.UUID(mine.id))
    assert (await world.resume.get(account, resume_id)).template == "organic"
    assert [t.id for t in (await world.resume.templates(account)).items] == ["organic", "plain"]


async def test_a_template_starts_from_a_pdf_whose_file_is_gone_once_read(
    world: World, database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """ADR 0041: only the style is read, on the worker; the stored file is
    deleted, and another user cannot see the reading."""
    from advisor.resume.infra.render import render_html, render_pdf
    from tests.unit.advisor.resume.builders import make_content

    spec = TemplateSpec(layout=Layout.SIDEBAR_LEFT, sidebar_kinds=(SectionKind.SKILLS,))
    pdf = render_pdf(render_html(make_content(), spec=spec, options=Options()))
    reading = await world.resume.upload_template_file(
        account, content_type="application/pdf", content=pdf
    )
    async with database.for_user(account) as session:
        key = (
            await session.execute(
                text("SELECT storage_key FROM resume.template_reading WHERE id = :id"),
                {"id": reading.id},
            )
        ).scalar_one()
    assert key.startswith(f"users/{account}/templatefiles/")
    assert world.store.get(key) == pdf

    await world.resume.read_template(account, reading.id)

    ready = await world.resume.template_reading(account, reading.id)
    assert ready.status == "ready" and ready.spec is not None
    assert ready.spec.layout is Layout.SIDEBAR_LEFT
    with pytest.raises(ClientError):
        world.store.get(key)
    with pytest.raises(NotFoundError):
        await world.resume.template_reading(other_account, reading.id)

    saved = await world.resume.create_template(
        account, name="From a file", spec=ready.spec.to_dict()
    )
    assert not saved.is_built_in
    await world.resume.forget_template_reading(account, reading.id)
    with pytest.raises(NotFoundError):
        await world.resume.template_reading(account, reading.id)


async def _answer_org(world: World, account: uuid.UUID, ref: TargetRef) -> str:
    """The user answers Fill the gap's one question, about org influence."""
    world.stub.replies.append(
        json.dumps(
            {
                "questions": [
                    {
                        "gap_key": ORG_KEY,
                        "text": "Did another team build on a design you wrote?",
                        "asked_because": "Nothing speaks to influence beyond a team.",
                        "answer_type": "free_text",
                        "choices": [],
                    }
                ]
            }
        )
    )
    questions = await world.gapfill.request(account, ref)
    await world.gapfill.write(account, questions.id)
    written = await world.gapfill.get(account, questions.id)
    assert written.status == "ready", written.error_message
    done = await world.gapfill.submit(
        account,
        written.id,
        [Answer(question_id=written.questions[0].id, text="Payments built on my ledger RFC.")],
    )
    [answer_id] = done.evidence_ids
    return str(answer_id)


def _claiming_org(cited: str, *, org_cites: str) -> str:
    reply = json.loads(_resume_reply(cited))
    reply["sections"][1]["entries"][0]["bullets"].append(
        {
            "text": "Wrote the ledger RFC the payments team built on",
            "evidence_ids": [org_cites],
            "answers": ORG,
        }
    )
    return json.dumps(reply)


async def test_a_gap_the_user_answered_about_is_claimed_from_the_answer_alone(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """A requirement nothing else covers rests on what the user answered
    about it, and on nothing else (ADR 0044)."""
    ref = await _own_posting(world, account)
    answer_id = await _answer_org(world, account, ref)
    assert await world.gapfill.get_answers(other_account, ref) == ()
    profile = await world.profile.snapshot(account)
    handle = {str(e.id): f"E{n}" for n, e in enumerate(profile.evidence, start=1)}

    cited = handle[world.evidence_id]
    world.stub.replies.append(_claiming_org(cited, org_cites=handle[answer_id]))
    requested = await world.resume.request(
        account, ref, template=Template.ORGANIC, options=Options()
    )
    await world.resume.generate(account, requested.id)

    view = await world.resume.get(account, requested.id)
    assert view.summary.status == "ready", view.summary.error_message
    assert f"gap: {ORG} (answered in [{handle[answer_id]}])" in world.stub.calls[-1].user
    org = next(c for c in view.coverage if c.requirement == ORG)
    assert org.verdict == "gap"
    assert [a.id for a in org.answers] == [answer_id]
    assert view.content is not None
    claimed = [b for b in view.content.bullets() if b.answers == ORG]
    assert [b.evidence_ids for b in claimed] == [(answer_id,)]

    # Claiming the same gap from other evidence keeps the line and drops the
    # claim (ADR 0046).
    world.stub.replies.append(_claiming_org(cited, org_cites=cited))
    again = await world.resume.request(account, ref, template=Template.ORGANIC, options=Options())
    await world.resume.generate(account, again.id)
    written = await world.resume.get(account, again.id)
    assert written.summary.status == "ready", written.summary.error_message
    assert written.content is not None
    line = next(b for b in written.content.bullets() if b.text.startswith("Wrote the ledger RFC"))
    assert (line.answers, line.evidence_ids) == (None, (world.evidence_id,))


async def test_a_resume_keeps_its_own_fonts_and_the_database_refuses_others(
    world: World, account: uuid.UUID, database: Database
) -> None:
    """ADR 0047, migration 0041."""
    resume_id = await _written(world, account)

    await world.resume.update_settings(
        account,
        resume_id,
        template=Template.PLAIN,
        options=Options(),
        heading_font="DejaVu Serif",
        body_font="DejaVu Sans Mono",
    )

    view = await world.resume.get(account, resume_id)
    assert (view.heading_font, view.body_font) == ("DejaVu Serif", "DejaVu Sans Mono")
    with pytest.raises(IntegrityError, match="ck_resume_body_font"):
        async with database.for_user(account) as session:
            await session.execute(
                text("UPDATE resume.resume SET body_font = 'Comic Sans' WHERE id = :id"),
                {"id": resume_id},
            )


async def test_a_resume_can_set_each_of_the_fonts_added_later(
    world: World, account: uuid.UUID
) -> None:
    """Migration 0043 widened the database's check to the whole list."""
    resume_id = await _written(world, account)

    for heading, body in (("Merriweather", "Inter"), ("EB Garamond", "IBM Plex Mono")):
        await world.resume.update_settings(
            account,
            resume_id,
            template=Template.PLAIN,
            options=Options(),
            heading_font=heading,
            body_font=body,
        )
        view = await world.resume.get(account, resume_id)
        assert (view.heading_font, view.body_font) == (heading, body)
