"""Role-map use cases against in-memory storage: what they store and announce,
with no database, no model and no embedding model."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from advisor.market import PostingView, SalaryRange, Visibility
from advisor.rolemap import (
    MAX_STRENGTHS,
    CandidateInput,
    MarketWait,
    RoleMapService,
    StrengthInput,
    get_posting_fit_result,
    get_projection_digest,
)
from advisor.rolemap import service as rolemap_service
from advisor.rolemap.domain import (
    BarBasis,
    HiringBar,
    RoleChange,
    RoleFitsComputed,
    RoleLineage,
    RoleMapBuildFinished,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    reconcile,
)
from advisor.rolemap.service import _RoleExtraction
from kernel.errors import ValidationError
from tests.unit.advisor.rolemap.fakes import MARKET_AS_OF, FakeMarket, FakeRoleMapUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")
# The build a recluster is the work of; the fakes need no row for it.
BUILD = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def _service(
    uow: FakeRoleMapUnitOfWork,
    market: FakeMarket | None = None,
    gateway: Any = None,
    *,
    top_k: int = 10,
    candidate_count: int = 20,
) -> RoleMapService:
    return RoleMapService(
        uow,
        market=market or FakeMarket(),  # type: ignore[arg-type]
        gateway=gateway,
        embedding_model="test-model",
        top_k=top_k,
        candidate_count=candidate_count,
    )


def _posting(title: str, *, company: str = "Acme") -> PostingView:
    return PostingView(
        id=uuid.uuid4(),
        company_name=company,
        title=title,
        location="Berlin",
        url=None,
        description="Build it.",
        visibility=Visibility.SHARED,
        salary=None,
    )


def _extraction(name: str, weights: tuple[float, ...] = (0.4, 0.9)) -> _RoleExtraction:
    return _RoleExtraction.model_validate(
        {
            "name": name,
            "requirements": [
                {"statement": f"skill {w}", "weight": w, "expected_level": "senior"}
                for w in weights
            ],
        }
    )


_BAR = HiringBar(value=70, confidence=0.6, basis=BarBasis.ESTIMATED, sample_size=0)


async def _store(
    service: RoleMapService, role_id: uuid.UUID, postings: list[PostingView], name: str
) -> None:
    await service._store_role(
        OWNER,
        role_id=role_id,
        keys={str(p.id) for p in postings},
        postings=postings,
        extraction=_extraction(name),
        bar=_BAR,
        bar_reasoning="because",
        model_id="model",
        template_version="v1",
    )


async def test_storing_a_role_replaces_its_members_and_requirements() -> None:
    uow = FakeRoleMapUnitOfWork()
    postings = [_posting("Backend"), _posting("Platform")]
    rolemap = _service(uow, FakeMarket(postings))
    role_id = uuid.uuid4()

    await _store(rolemap, role_id, postings, "Backend Engineer")
    await _store(rolemap, role_id, postings[:1], "Senior Backend Engineer")

    [role] = await rolemap.roles(OWNER)
    assert role.name == "Senior Backend Engineer" and role.opening_count == 1
    assert role.hiring_bar == 70 and role.bar_basis == "estimated"
    # Weightiest requirement first, whatever order they were stored in.
    assert [r.weight for r in role.requirements] == [0.9, 0.4]
    assert len(uow.store.members) == 1 and len(uow.store.requirements) == 2
    [(same, members)] = await rolemap.role_postings(OWNER)
    assert same.id == role_id and [p.title for p in members] == ["Backend"]
    assert (
        uow.store.events
        == [RoleRequirementsChanged(owner_id=OWNER, role_id=role_id, requirements=2)] * 2
    )


async def test_a_role_is_stored_without_the_work_arrangement_its_name_came_with() -> None:
    uow = FakeRoleMapUnitOfWork()
    postings = [_posting("Data Scientist")]
    rolemap = _service(uow, FakeMarket(postings))

    await _store(rolemap, uuid.uuid4(), postings, "Senior Data Scientist (Remote)")

    [role] = await rolemap.roles(OWNER)
    assert role.name == "Senior Data Scientist"


async def test_keeping_a_role_refreshes_only_what_needs_no_model() -> None:
    uow = FakeRoleMapUnitOfWork()
    postings = [_posting("Backend"), _posting("Platform")]
    rolemap = _service(uow, FakeMarket(postings))
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, postings[:1], "Backend Engineer")

    assert await rolemap._keep_role(OWNER, role_id=role_id, postings=postings)
    assert not await rolemap._keep_role(OWNER, role_id=uuid.uuid4(), postings=postings)

    [role] = await rolemap.roles(OWNER)
    assert role.opening_count == 2 and role.name == "Backend Engineer"


async def test_a_market_band_takes_in_postings_whose_location_names_the_market() -> None:
    uow = FakeRoleMapUnitOfWork()
    paid = [
        replace(
            _posting("Backend"),
            location="Berlin, Germany",
            salary=SalaryRange(80_000, 100_000, "EUR"),
        ),
        replace(
            _posting("Platform"),
            location="Munich, Germany",
            salary=SalaryRange(90_000, 110_000, "EUR"),
        ),
    ]
    rolemap = _service(uow, FakeMarket(paid, markets=["Berlin"]))
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, paid, "Backend Engineer")

    [role] = await rolemap.roles(OWNER)
    assert set(role.salary_bands) == {"Berlin"}
    assert role.salary_bands["Berlin"]["mid"] == 90_000
    assert role.salary_bands["Berlin"]["sample_size"] == 1


async def test_lineage_retires_what_is_gone_and_announces_splits() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    kept, gone = uuid.uuid4(), uuid.uuid4()
    await _store(rolemap, kept, [_posting("Backend")], "Backend")
    await _store(rolemap, gone, [_posting("Data")], "Data")
    uow.store.events.clear()

    reconciliation: Any = reconcile(
        previous={str(kept): {"a", "b", "c", "d"}, str(gone): {"x", "y"}},
        clusters=[{"a", "b"}, {"c", "d"}],
        new_id=lambda: str(uuid.uuid4()),
    )
    await rolemap._record_lineage(OWNER, reconciliation)

    assert [r.id for r in await rolemap.roles(OWNER)] == [kept]
    assert len(uow.store.lineage) == len(reconciliation.lineage)
    splits = tuple(
        e for e in reconciliation.lineage if e.kind in (RoleChange.SPLIT, RoleChange.MERGED)
    )
    expected: list[Any] = [RoleSplitOrMerged(owner_id=OWNER, changes=splits)] if splits else []
    expected.append(RolesReclustered(owner_id=OWNER, roles=2))
    assert uow.store.events == expected
    assert all(isinstance(e, RoleLineage) for e in splits)


async def test_a_role_merged_into_another_is_retired_and_recorded_once() -> None:
    """Left live, a merged-away role kept its old postings: a second bubble
    over the same openings, ranked in Top matched and scored every build."""
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, gateway=ProjectingGateway())
    kept, absorbed = uuid.uuid4(), uuid.uuid4()
    await _store(rolemap, kept, [_posting("Backend")], "Backend")
    await _store(rolemap, absorbed, [_posting("Platform")], "Platform")
    lineage_before = len(uow.store.lineage)

    await rolemap._record_lineage(
        OWNER,
        reconcile(
            previous={str(kept): {"a", "b", "c"}, str(absorbed): {"d"}},
            clusters=[{"a", "b", "c", "d"}],
            new_id=lambda: str(uuid.uuid4()),
        ),
    )

    assert [r.id for r in await rolemap.roles(OWNER)] == [kept]
    recorded = list(uow.store.lineage.values())[lineage_before:]
    assert [e.kind for e in recorded] == [RoleChange.MERGED]
    # And its fit is no longer scored: only live roles are projected.
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [], strengths=[StrengthInput("backend", "B", "r", 60, 0.9)]
    )
    assert [f.role_id for f in await rolemap.compute_fits(OWNER)] == [kept]


async def test_a_role_retired_by_an_earlier_build_is_not_retired_again() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    kept, gone = uuid.uuid4(), uuid.uuid4()
    await _store(rolemap, kept, [_posting("Backend")], "Backend")
    await _store(rolemap, gone, [_posting("Data")], "Data")

    def again() -> Any:
        return reconcile(
            previous={str(kept): {"a", "b"}, str(gone): {"x"}},
            clusters=[{"a", "b"}],
            new_id=lambda: str(uuid.uuid4()),
        )

    await rolemap._record_lineage(OWNER, again())
    retired_at = uow.store.roles[gone].retired_at
    lineage = len(uow.store.lineage)

    await rolemap._record_lineage(OWNER, again())

    assert uow.store.roles[gone].retired_at == retired_at
    assert len(uow.store.lineage) == lineage


async def test_the_map_counts_the_openings_a_role_has_now() -> None:
    """A bubble says what Top matched can list for its role: a posting gone
    from the user's scope since the build is not counted."""
    postings = [_posting(f"Backend {i}") for i in range(3)]
    market = FakeMarket(postings)
    rolemap = _service(FakeRoleMapUnitOfWork(), market)
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, postings, "Backend Engineer")

    market.postings = postings[:2]

    [drawn] = await rolemap.map_roles(OWNER)
    [stored] = await rolemap.roles(OWNER)
    assert (drawn.opening_count, stored.opening_count) == (2, 3)
    listed = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)
    assert len(listed) == drawn.opening_count


async def test_an_opening_in_two_roles_is_listed_under_each_role() -> None:
    """Each role's own list has it, as each bubble counts it; the top list,
    one per company, names it once."""
    shared = _posting("Staff Backend Engineer")
    rolemap = _service(FakeRoleMapUnitOfWork(), FakeMarket([shared]))
    first, second = uuid.uuid4(), uuid.uuid4()
    await _store(rolemap, first, [shared], "Backend Engineer")
    await _store(rolemap, second, [shared], "Staff Engineer")

    for role_id in (first, second):
        [listed] = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)
        assert (listed.role_id, listed.posting_id) == (role_id, shared.id)
    assert [m.posting_id for m in await rolemap.matched_postings(OWNER, limit=None)] == [shared.id]


async def test_top_matched_names_each_company_once_and_a_roles_list_keeps_all() -> None:
    """Across roles, one opening per company; one role's list stays whole, as
    its bubble counts it."""
    postings = [
        _posting("Backend A", company="G2i"),
        _posting("Backend B", company="G2i"),
        _posting("Backend C", company="Acme"),
    ]
    rolemap = _service(FakeRoleMapUnitOfWork(), FakeMarket(postings))
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, postings, "Backend Engineer")

    top = await rolemap.matched_postings(OWNER, limit=None)
    mine = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)
    [drawn] = await rolemap.map_roles(OWNER)

    assert sorted(m.company_name for m in top) == ["Acme", "G2i"]
    assert len(mine) == drawn.opening_count == 3


# --- builds (ADR 0006, ADR 0018) -------------------------------------------


async def test_a_build_with_nothing_due_runs_now_and_is_queued_once() -> None:
    market = FakeMarket(markets=["Taiwan"])
    service = _service(FakeRoleMapUnitOfWork(), market)

    first = await service.request_build(OWNER, wait=False)
    again = await service.request_build(OWNER, wait=False)

    assert first.should_queue and not first.should_await_market
    assert first.build.status == "running" and first.build.locations == ("Taiwan",)
    assert not again.should_queue and again.build.id == first.build.id
    # Asked once: the second request joined the open build.
    assert len(market.asked) == 1


async def test_a_build_asks_the_market_for_its_titles_and_places() -> None:
    uow = FakeRoleMapUnitOfWork()
    market = FakeMarket(markets=["Taiwan", "Europe"])
    service = _service(uow, market)
    await service.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Data Engineer", "d"), _candidate("ML Engineer", "m")]
    )

    await service.request_build(OWNER, wait=False)

    (asked,) = market.asked
    assert asked == {"titles": ["Data Engineer", "ML Engineer"], "places": ["Taiwan", "Europe"]}


async def test_a_build_with_due_sources_waits_for_them_and_then_starts() -> None:
    due = (uuid.uuid4(), uuid.uuid4())
    market = FakeMarket(due=due)
    service = _service(FakeRoleMapUnitOfWork(), market)

    requested = await service.request_build(OWNER, wait=False)

    assert not requested.should_queue and requested.should_await_market
    assert requested.build.status == "waiting" and requested.build.is_waiting_for_market
    wait = timedelta(minutes=5)
    assert await service.check_market(OWNER, requested.build.id, deadline=wait) is MarketWait.WAIT

    market.fetched.update(due)
    assert await service.check_market(OWNER, requested.build.id, deadline=wait) is MarketWait.START
    latest = await service.latest_build(OWNER)
    assert latest is not None and latest.status == "running"
    # Started once: a second check finds nothing to do.
    assert await service.check_market(OWNER, requested.build.id, deadline=wait) is MarketWait.DONE


async def test_a_build_starts_at_its_deadline_on_what_is_stored() -> None:
    market = FakeMarket(due=(uuid.uuid4(),))
    service = _service(FakeRoleMapUnitOfWork(), market)
    requested = await service.request_build(OWNER, wait=False)

    found = await service.check_market(OWNER, requested.build.id, deadline=timedelta(0))

    assert found is MarketWait.START


async def test_a_build_asked_for_during_an_analysis_asks_the_market_once_it_is_released() -> None:
    market = FakeMarket()
    service = _service(FakeRoleMapUnitOfWork(), market)

    waiting = await service.request_build(OWNER, wait=True)
    assert not waiting.should_queue and waiting.build.status == "waiting"
    assert not waiting.build.is_waiting_for_market and market.asked == []
    assert (await service.request_build(OWNER, wait=True)).build.id == waiting.build.id

    released = await service.release_waiting(OWNER)

    assert released is not None and released.build.id == waiting.build.id
    assert released.should_queue and released.build.status == "running"
    assert len(market.asked) == 1
    assert await service.release_waiting(OWNER) is None


async def test_asking_again_once_nothing_is_running_releases_the_waiting_build() -> None:
    service = _service(FakeRoleMapUnitOfWork())
    waiting = await service.request_build(OWNER, wait=True)

    now = await service.request_build(OWNER, wait=False)

    assert now.should_queue and now.build.id == waiting.build.id
    assert now.build.status == "running"


async def test_a_build_already_waiting_for_the_market_is_joined_not_asked_again() -> None:
    market = FakeMarket(due=(uuid.uuid4(),))
    service = _service(FakeRoleMapUnitOfWork(), market)
    first = await service.request_build(OWNER, wait=False)

    again = await service.request_build(OWNER, wait=False)

    assert again.build.id == first.build.id
    assert not again.should_queue and not again.should_await_market
    assert len(market.asked) == 1


async def test_a_finished_build_is_ready_and_the_next_request_is_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(FakeRoleMapUnitOfWork())
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID, build_id: uuid.UUID) -> list[Any]:
        return []

    monkeypatch.setattr(service, "recluster", recluster)

    assert await service.build(OWNER, requested.build.id) == []

    latest = await service.latest_build(OWNER)
    assert latest is not None and latest.status == "ready" and latest.finished_at is not None
    # It says how old the market it read was.
    assert latest.market_data_at == MARKET_AS_OF
    finished = await service.last_finished_build(OWNER)
    assert finished is not None and finished.id == requested.build.id
    assert (await service.request_build(OWNER, wait=False)).build.id != requested.build.id


async def test_a_failed_build_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(FakeRoleMapUnitOfWork())
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID, build_id: uuid.UUID) -> list[Any]:
        raise ValidationError("no market chosen")

    monkeypatch.setattr(service, "recluster", recluster)

    assert await service.build(OWNER, requested.build.id) == []
    latest = await service.latest_build(OWNER)
    assert latest is not None and (latest.status, latest.error_code) == (
        "failed",
        "validation_failed",
    )


async def test_a_build_that_stops_unexpectedly_is_recorded_and_still_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(FakeRoleMapUnitOfWork())
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID, build_id: uuid.UUID) -> list[Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "recluster", recluster)

    with pytest.raises(RuntimeError):
        await service.build(OWNER, requested.build.id)
    latest = await service.latest_build(OWNER)
    assert latest is not None and (latest.status, latest.error_code) == ("failed", "internal")


async def test_a_waiting_build_is_not_run_by_its_job() -> None:
    service = _service(FakeRoleMapUnitOfWork())
    waiting = await service.request_build(OWNER, wait=True)

    assert await service.build(OWNER, waiting.build.id) == []
    latest = await service.latest_build(OWNER)
    assert latest is not None and latest.status == "waiting"


async def test_builds_are_per_user() -> None:
    service = _service(FakeRoleMapUnitOfWork())
    mine = await service.request_build(OWNER, wait=False)

    theirs = await service.request_build(OTHER, wait=False)

    assert theirs.should_queue and theirs.build.id != mine.build.id


class _Reply:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.model_id = "claude-opus-5"
        self.template_version = "v1"


class ScriptedGateway:
    """Answers extraction and difficulty calls, and records what it was shown."""

    def __init__(self) -> None:
        self.shown: list[str] = []

    async def run(self, owner_id: uuid.UUID, *, task: str, inputs: dict[str, str], **_: Any):
        self.shown.append(inputs["postings"])
        if task == "rolemap.extract":
            return _Reply(_extraction("Whatever the model calls it"))
        from advisor.rolemap.service import _DifficultyEstimate

        return _Reply(_DifficultyEstimate(difficulty=60, confidence=0.5, reasoning="A guess."))


# --- the fit kit, for Target (ADR 0033) -------------------------------------


class OwnPostingGateway:
    """Reads a JD's requirements, then maps them: ``skill 0.9`` onto
    ``backend``, wanted at ``target``, and ``skill 0.4`` onto nothing the user
    has. Records each call's task."""

    def __init__(self, target: int = 80) -> None:
        self.target = target
        self.tasks: list[str] = []
        self.shown: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, task: str, inputs: dict[str, str], **_: Any):
        from advisor.rolemap.service import _Projection

        self.tasks.append(task)
        self.shown.append(inputs)
        if task == "rolemap.extract":
            return _Reply(_extraction("Whatever the model calls it"))
        return _Reply(
            _Projection.model_validate(
                {
                    "mappings": [
                        {"requirement_statement": "skill 0.9", "dimension_id": "backend"},
                        {"requirement_statement": "skill 0.4", "dimension_id": "nowhere"},
                    ],
                    "target_scores": [
                        {"dimension_id": "backend", "target": self.target},
                        {"dimension_id": "invented", "target": 90},
                    ],
                    "reasoning": "Close on services.",
                }
            )
        )

    async def estimate(self, owner_id: uuid.UUID, **_: Any) -> _Estimated:
        return _Estimated()


async def _with_strengths(rolemap: RoleMapService, *, backend: int = 60) -> uuid.UUID:
    assessment_id = uuid.uuid4()
    await rolemap.replace_candidates(
        OWNER,
        assessment_id,
        [],
        strengths=[StrengthInput("backend", "Backend", "Built services.", backend, 0.9)],
    )
    return assessment_id


async def test_the_strengths_a_fit_is_scored_against_are_the_latest_analysiss() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())
    assert await rolemap.strengths(OWNER) is None

    assessment_id = await _with_strengths(rolemap, backend=70)

    strengths = await rolemap.strengths(OWNER)
    assert strengths is not None
    assert (strengths.assessment_id, strengths.scores) == (assessment_id, {"backend": 70})


async def test_a_jds_requirements_are_read_weightiest_first_and_stored_nowhere() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = OwnPostingGateway()
    rolemap = _service(uow, gateway=gateway)

    read = await rolemap.extract_requirements(
        OWNER, title="Staff Engineer", company_name=None, job_description="Own the ledger."
    )

    assert gateway.tasks == ["rolemap.extract"]
    assert "Own the ledger" in gateway.shown[0]["postings"]
    assert [(r.statement, r.weight) for r in read.requirements] == [
        ("skill 0.9", 0.9),
        ("skill 0.4", 0.4),
    ]
    assert uow.store.roles == {} and uow.store.requirements == {}


async def test_a_jobs_requirements_are_estimated_from_its_title_alone() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = OwnPostingGateway()
    rolemap = _service(uow, gateway=gateway)

    read = await rolemap.infer_requirements(OWNER, title="Platform Lead", company_name=None)

    assert gateway.tasks == ["rolemap.extract"]
    assert gateway.shown[0] == {"job": "Platform Lead — company not stated"}
    assert [r.statement for r in read.requirements] == ["skill 0.9", "skill 0.4"]
    assert uow.store.roles == {} and uow.store.requirements == {}


async def test_projecting_requirements_keeps_only_the_users_dimensions() -> None:
    gateway = OwnPostingGateway(target=80)
    rolemap = _service(FakeRoleMapUnitOfWork(), gateway=gateway)
    assessment_id = await _with_strengths(rolemap)
    read = await rolemap.extract_requirements(
        OWNER, title="Staff Engineer", company_name=None, job_description="Own it."
    )

    projection = await rolemap.project_requirements(
        OWNER, title="Staff Engineer", requirements=read.requirements
    )

    assert projection.assessment_id == assessment_id
    assert projection.requirement_map == {"skill 0.9": "backend", "skill 0.4": None}
    assert projection.target_profile == {"backend": 80}
    assert projection.requirements_digest == get_projection_digest(read.requirements)
    result = get_posting_fit_result(
        requirements=projection.requirements,
        requirement_map=projection.requirement_map,
        target_profile=projection.target_profile,
        user_scores={"backend": 60},
    )
    assert [(g["dimension_key"], g["delta"]) for g in result.gaps] == [("backend", -20)]
    assert [u["statement"] for u in result.uncovered] == ["skill 0.4"]


async def test_projecting_needs_an_analysis_and_some_requirements() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork(), gateway=OwnPostingGateway())
    read = await rolemap.extract_requirements(
        OWNER, title="Staff Engineer", company_name=None, job_description="Own it."
    )

    with pytest.raises(ValidationError):
        await rolemap.project_requirements(
            OWNER, title="Staff Engineer", requirements=read.requirements
        )
    await _with_strengths(rolemap)
    with pytest.raises(ValidationError):
        await rolemap.project_requirements(OWNER, title="Staff Engineer", requirements=())


# --- recommended roles from the analysis's candidates (ADR 0024) ------------

# A stand-in embedding: each keyword a text contains adds weight on its axis.
_AXES = ("backend", "payments", "designer", "data")


def _fake_embed(texts: list[str], *, model_name: str) -> list[list[float]]:
    return [[float(text.lower().count(word)) for word in _AXES] for text in texts]


@pytest.fixture
def embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rolemap_service, "embed", _fake_embed)


def _candidate(title: str, description: str) -> CandidateInput:
    return CandidateInput(title=title, description=description, dimension_keys=("backend",))


def _market(backend: int = 3, designer: int = 0) -> FakeMarket:
    return FakeMarket(
        [_posting(f"Backend Engineer {i}") for i in range(backend)]
        + [_posting(f"Designer {i}") for i in range(designer)]
    )


async def test_an_analysiss_candidates_replace_the_last_ones_in_its_order() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    assessment = uuid.uuid4()
    await rolemap.replace_candidates(OWNER, uuid.uuid4(), [_candidate("Old", "old work")])

    await rolemap.replace_candidates(
        OWNER, assessment, [_candidate("First", "a"), _candidate("Second", "b")]
    )

    found = await rolemap.candidates(OWNER)
    assert [(c.rank, c.title, c.role_id) for c in found] == [
        (0, "First", None),
        (1, "Second", None),
    ]
    assert {c.assessment_id for c in uow.store.candidates.values()} == {assessment}


async def test_candidates_come_with_the_strengths_that_weigh_them_and_announce_nothing() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [_candidate("First", "a")],
        strengths=[StrengthInput("old", "Old", "read", 50, 1.0)],
    )

    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [_candidate("Second", "b")],
        strengths=[
            StrengthInput("backend", "Backend", "Built services.", 90, 0.8),
            StrengthInput("data", "Data", "Some pipelines.", 100, 1.0),
        ],
    )

    stored = {
        s.dimension_key: (s.score, s.confidence, s.weight) for s in uow.store.strengths.values()
    }
    # Replaced with the candidates; the weight is score times confidence, and
    # the score itself is kept for the fits (ADR 0028).
    assert stored == {"backend": (90, 0.8, pytest.approx(0.72)), "data": (100, 1.0, 1.0)}
    # The market is asked by the build that follows, not told here (ADR 0027).
    assert uow.store.events == []


@pytest.mark.parametrize(
    "strength",
    [
        StrengthInput("backend", "Backend", "read", 120, 0.5),
        StrengthInput("backend", "Backend", "read", 60, 1.5),
    ],
)
async def test_a_strength_off_its_scale_is_refused(strength: StrengthInput) -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())

    with pytest.raises(ValidationError, match="scored 0 to 100"):
        await rolemap.replace_candidates(OWNER, uuid.uuid4(), [], strengths=[strength])


async def test_no_more_dimensions_are_handed_over_than_a_fit_is_priced_for() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())
    too_many = [StrengthInput(f"d{i}", "D", "read", 50, 0.5) for i in range(MAX_STRENGTHS + 1)]

    with pytest.raises(ValidationError, match="at most"):
        await rolemap.replace_candidates(OWNER, uuid.uuid4(), [], strengths=too_many)


async def test_an_analysis_recommends_no_more_roles_than_configured() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork(), top_k=3, candidate_count=5)
    too_many = [_candidate(f"Role {i}", "work") for i in range(6)]

    with pytest.raises(ValidationError, match="at most 5"):
        await rolemap.replace_candidates(OWNER, uuid.uuid4(), too_many)


@pytest.mark.parametrize(("top_k", "candidate_count"), [(0, 10), (11, 10)])
def test_a_build_keeps_between_one_and_every_candidate(top_k: int, candidate_count: int) -> None:
    with pytest.raises(ValueError, match="between 1 and candidate_count"):
        _service(FakeRoleMapUnitOfWork(), top_k=top_k, candidate_count=candidate_count)


@pytest.mark.usefixtures("embedded")
async def test_only_the_top_k_are_named_and_analysed() -> None:
    """Three candidates on the market and k = 2: the third is kept unplaced,
    with its openings counted, and nothing is sent to the model for it
    (ADR 0029)."""
    gateway = ScriptedGateway()
    market = FakeMarket(
        [_posting(f"Backend Engineer {i}") for i in range(3)]
        + [_posting(f"Designer {i}") for i in range(3)]
        + [_posting(f"Data Platform {i}") for i in range(3)]
    )
    rolemap = _service(FakeRoleMapUnitOfWork(), market, gateway, top_k=2, candidate_count=3)
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [
            _candidate("Backend Engineer", "Backend services."),
            _candidate("Designer", "Designer work."),
            _candidate("Data Engineer", "Data pipelines."),
        ],
    )

    roles = await rolemap.recluster(OWNER, BUILD)

    assert len(roles) == 2
    assert len(gateway.shown) == 2 * 2  # extraction and difficulty, per kept role
    backend, designer, data = await rolemap.candidates(OWNER)
    assert backend.role_id is not None and designer.role_id is not None
    assert (data.role_id, data.opening_count) == (None, 3)


async def test_a_build_is_priced_for_k_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    market = _market(backend=60)
    rolemap = _service(FakeRoleMapUnitOfWork(), market, ProjectingGateway(), top_k=3)

    assert (await rolemap.estimate_cost(OWNER))["max_roles"] == 3

    # A search will run first, so nothing stored bounds it below k.
    async def searchable(owner_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(market, "has_searchable_place", searchable)
    thin = _service(FakeRoleMapUnitOfWork(), market, ProjectingGateway(), top_k=4)
    market.postings = []
    assert (await thin.estimate_cost(OWNER))["max_roles"] == 4
    assert (await thin.estimate_fits(OWNER, recommended=10))["roles"] == 4


async def test_candidates_are_per_user() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())
    await rolemap.replace_candidates(OWNER, uuid.uuid4(), [_candidate("Mine", "work")])

    assert await rolemap.candidates(OTHER) == []


@pytest.mark.usefixtures("embedded")
async def test_without_candidates_a_build_names_no_recommended_role() -> None:
    """No analysis has succeeded, so nothing the user priced exists to spend on."""
    gateway = ScriptedGateway()
    rolemap = _service(FakeRoleMapUnitOfWork(), _market(), gateway)

    assert await rolemap.recluster(OWNER, BUILD) == []
    assert gateway.shown == []


@pytest.mark.usefixtures("embedded")
async def test_a_candidate_the_market_has_becomes_a_role_named_from_its_openings() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = ScriptedGateway()
    rolemap = _service(uow, _market(backend=3, designer=1), gateway)
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )

    [role] = await rolemap.recluster(OWNER, BUILD)

    assert role.name == "Whatever the model calls it" and role.opening_count == 3
    assert "Designer" not in gateway.shown[0]
    [candidate] = await rolemap.candidates(OWNER)
    assert (candidate.role_id, candidate.opening_count) == (role.id, 3)


@pytest.mark.usefixtures("embedded")
async def test_what_a_candidates_search_found_is_its_and_a_loose_hit_is_left_out() -> None:
    """Payments Lead came back from the data search, matched on its description;
    it is nothing like a data role, and the payments candidate never searched
    for it, so it is nobody's opening (ADR 0027)."""
    data = [_posting(f"Data Platform {i}") for i in range(3)]
    loose = _posting("Payments Lead")
    market = FakeMarket([*data, loose], searched={"Data Engineer": [p.id for p in [*data, loose]]})
    rolemap = _service(FakeRoleMapUnitOfWork(), market, ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [_candidate("Data Engineer", "Data pipelines."), _candidate("Payments Engineer", "")],
        strengths=[StrengthInput("backend", "Data", "Data pipelines.", 80, 1.0)],
    )

    [role] = await rolemap.recluster(OWNER, BUILD)

    [(_, openings)] = await rolemap.role_postings(OWNER)
    assert {p.title for p in openings} == {p.title for p in data}
    data_candidate, payments = await rolemap.candidates(OWNER)
    assert (data_candidate.role_id, data_candidate.opening_count) == (role.id, 3)
    assert payments.opening_count == 0
    # The estimate that chose it is kept beside it, never shown as a fit.
    assert data_candidate.fit_estimate is not None


@pytest.mark.usefixtures("embedded")
async def test_a_candidate_the_market_lacks_is_left_unplaced_and_costs_nothing() -> None:
    gateway = ScriptedGateway()
    rolemap = _service(FakeRoleMapUnitOfWork(), _market(backend=3), gateway)
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [
            _candidate("Payments Engineer", "Payments systems."),
            _candidate("Backend Engineer", "Backend services."),
        ],
    )

    [role] = await rolemap.recluster(OWNER, BUILD)

    payments, backend = await rolemap.candidates(OWNER)
    assert (payments.role_id, payments.opening_count) == (None, 0)
    assert backend.role_id == role.id
    assert len(gateway.shown) == 2  # extraction and difficulty, for one role


@pytest.mark.usefixtures("embedded")
async def test_a_rebuild_on_an_unchanged_market_costs_nothing() -> None:
    gateway = ScriptedGateway()
    rolemap = _service(FakeRoleMapUnitOfWork(), _market(backend=3), gateway)
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    [first] = await rolemap.recluster(OWNER, BUILD)
    calls = len(gateway.shown)

    [again] = await rolemap.recluster(OWNER, BUILD)

    assert again.id == first.id and len(gateway.shown) == calls


@pytest.mark.usefixtures("embedded")
async def test_a_new_analysiss_candidates_retire_the_roles_they_no_longer_include() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, _market(backend=3, designer=3), ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    [backend] = await rolemap.recluster(OWNER, BUILD)

    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Designer", "Designer work.")]
    )
    [designer] = await rolemap.recluster(OWNER, BUILD)

    assert designer.id != backend.id
    assert uow.store.roles[backend.id].retired_at is not None


@pytest.mark.usefixtures("embedded")
async def test_an_empty_market_keeps_the_roles_it_says_nothing_about() -> None:
    uow = FakeRoleMapUnitOfWork()
    market = _market(backend=3)
    rolemap = _service(uow, market, ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    [role] = await rolemap.recluster(OWNER, BUILD)
    market.postings = []

    assert [r.id for r in await rolemap.recluster(OWNER, BUILD)] == [role.id]
    [candidate] = await rolemap.candidates(OWNER)
    assert candidate.role_id == role.id


@pytest.mark.usefixtures("embedded")
async def test_candidates_replaced_during_a_build_are_left_for_the_next_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rolemap = _service(FakeRoleMapUnitOfWork(), _market(backend=3), ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    record = rolemap._record_lineage

    async def analysis_finishes_meanwhile(owner_id: uuid.UUID, reconciliation: Any) -> None:
        await record(owner_id, reconciliation)
        await rolemap.replace_candidates(
            OWNER, uuid.uuid4(), [_candidate("Designer", "Designer work.")]
        )

    monkeypatch.setattr(rolemap, "_record_lineage", analysis_finishes_meanwhile)

    await rolemap.recluster(OWNER, BUILD)

    [candidate] = await rolemap.candidates(OWNER)
    assert (candidate.title, candidate.role_id) == ("Designer", None)


@pytest.mark.usefixtures("embedded")
async def test_a_build_records_what_it_made_of_each_candidate_and_leaves_them_alone() -> None:
    """The candidate is the query; the outcome is the build's record (Phase 8)."""
    uow = FakeRoleMapUnitOfWork()
    market = FakeMarket(
        [_posting(f"Backend Engineer {i}") for i in range(3)]
        + [_posting(f"Designer {i}") for i in range(3)]
        + [_posting("Data Platform 0")]
    )
    rolemap = _service(uow, market, ScriptedGateway(), top_k=1)
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [
            _candidate("Backend Engineer", "Backend services."),
            _candidate("Designer", "Designer work."),
            _candidate("Data Engineer", "Data pipelines."),
        ],
    )
    stored = {c.id: c for c in uow.store.candidates.values()}

    [role] = await rolemap.recluster(OWNER, BUILD)

    placements = sorted(uow.store.placements.values(), key=lambda p: p.rank)
    assert [(p.title, str(p.outcome)) for p in placements] == [
        ("Backend Engineer", "placed"),
        ("Designer", "outside_top_k"),
        ("Data Engineer", "too_few_openings"),
    ]
    assert placements[0].role_id == role.id and placements[0].opening_count == 3
    assert (placements[1].role_id, placements[1].opening_count) == (None, 3)
    assert placements[2].fit_estimate is None
    assert {p.build_run_id for p in placements} == {BUILD}
    # The candidates themselves are untouched: still only the query.
    assert {c.id: c for c in uow.store.candidates.values()} == stored
    candidates = await rolemap.candidates(OWNER)
    assert [c.outcome for c in candidates] == ["placed", "outside_top_k", "too_few_openings"]


@pytest.mark.usefixtures("embedded")
async def test_the_candidates_read_the_newest_build_that_placed_them() -> None:
    uow = FakeRoleMapUnitOfWork()
    market = _market(backend=3)
    rolemap = _service(uow, market, ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    await rolemap.recluster(OWNER, BUILD)
    # Two of its three openings go; the market still has enough to build on.
    market.postings = [*market.postings[:1], _posting("Designer 0"), _posting("Designer 1")]

    later = uuid.uuid4()
    await rolemap.recluster(OWNER, later)

    [candidate] = await rolemap.candidates(OWNER)
    assert (candidate.outcome, candidate.role_id, candidate.opening_count) == (
        "too_few_openings",
        None,
        1,
    )
    # The first build's record is kept beside the second's.
    assert {p.build_run_id for p in uow.store.placements.values()} == {BUILD, later}


# --- fits, scored once per build (ADR 0024) ---------------------------------


async def test_a_finished_build_announces_itself_for_its_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeRoleMapUnitOfWork()
    service = _service(uow)
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID, build_id: uuid.UUID) -> list[Any]:
        return []

    monkeypatch.setattr(service, "recluster", recluster)
    await service.build(OWNER, requested.build.id)

    assert RoleMapBuildFinished(OWNER, requested.build.id, "ready") in uow.store.events


async def test_a_failed_build_still_announces_itself_for_its_fits() -> None:
    uow = FakeRoleMapUnitOfWork()
    service = _service(uow)
    requested = await service.request_build(OWNER, wait=False)

    await service.fail_build(OWNER, requested.build.id, code="stale", message="Lost.")
    await service.fail_build(OWNER, requested.build.id, code="stale", message="Lost.")

    finished = [e for e in uow.store.events if isinstance(e, RoleMapBuildFinished)]
    assert finished == [RoleMapBuildFinished(OWNER, requested.build.id, "failed")]


# --- fits (ADR 0028) ---------------------------------------------------------


class _Estimated:
    cost_usd = Decimal("0.10")
    model_id = "claude-opus-5"
    rate_is_published = True


class ProjectingGateway:
    """Answers fit projections: every requirement maps to ``backend``, which the
    role wants at ``target``. Records what it was shown."""

    def __init__(self, target: int = 80) -> None:
        self.target = target
        self.shown: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, task: str, inputs: dict[str, str], **_: Any):
        from advisor.rolemap.service import _Projection

        assert task == "rolemap.fit"
        self.shown.append(inputs)
        return _Reply(
            _Projection.model_validate(
                {
                    "mappings": [
                        {"requirement_statement": "skill 0.9", "dimension_id": "backend"},
                        {"requirement_statement": "skill 0.4", "dimension_id": "nowhere"},
                    ],
                    "target_scores": [
                        {"dimension_id": "backend", "target": self.target},
                        {"dimension_id": "invented", "target": 90},
                    ],
                    "reasoning": "Close on services, nothing on the rest.",
                }
            )
        )

    async def estimate(self, owner_id: uuid.UUID, **_: Any) -> _Estimated:
        return _Estimated()


async def _scored_map(gateway: Any) -> tuple[RoleMapService, FakeRoleMapUnitOfWork, uuid.UUID]:
    """One analysed role, and the strengths an analysis handed over."""
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, FakeMarket([_posting("Backend")]), gateway)
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, [_posting("Backend")], "Backend Engineer")
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [],
        strengths=[
            StrengthInput("backend", "Backend", "Built services.", 60, 0.9),
            StrengthInput("data", "Data", "Some pipelines.", 40, 0.5),
        ],
    )
    return rolemap, uow, role_id


async def test_a_fit_is_scored_against_the_strengths_the_analysis_handed_over() -> None:
    gateway = ProjectingGateway(target=80)
    rolemap, uow, role_id = await _scored_map(gateway)

    [fit] = await rolemap.compute_fits(OWNER)

    # The prompt names the user's own scores, from the hand-over.
    assert "backend: Backend — scored 60/100 (confidence 0.90)" in gateway.shown[0]["dimensions"]
    assert fit.role_id == role_id
    # A target on a dimension the user lacks is the model drifting: dropped.
    assert fit.target_profile == {"backend": 80}
    assert [(g["dimension_key"], g["delta"]) for g in fit.gaps] == [("backend", -20)]
    # A requirement mapped nowhere the user has is uncovered, not dropped.
    assert [u["statement"] for u in fit.uncovered] == ["skill 0.4"]
    assert fit.requirement_map == {"skill 0.9": "backend", "skill 0.4": None}
    assert fit.assessment_id == next(iter(uow.store.strengths.values())).assessment_id
    assert RoleFitsComputed(owner_id=OWNER, roles=1) in uow.store.events


async def test_fits_need_an_analysis_to_score_against() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, FakeMarket([_posting("Backend")]), ProjectingGateway())
    await _store(rolemap, uuid.uuid4(), [_posting("Backend")], "Backend Engineer")

    with pytest.raises(ValidationError, match="run an analysis"):
        await rolemap.compute_fits(OWNER)


async def test_the_current_fit_is_the_newest_per_role() -> None:
    rolemap, uow, role_id = await _scored_map(ProjectingGateway(target=90))
    await rolemap.compute_fits(OWNER)
    rolemap._gateway = ProjectingGateway(target=60)  # type: ignore[assignment]
    # A new analysis, so the role is scored again rather than reused.
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [],
        strengths=[StrengthInput("backend", "Backend", "Built services.", 60, 0.9)],
    )
    await rolemap.compute_fits(OWNER)

    [fit] = await rolemap.fits(OWNER)

    assert len(uow.store.fits) == 2
    assert (fit.role_id, fit.target_profile) == (role_id, {"backend": 60})


async def test_an_unchanged_role_against_unchanged_scores_is_not_scored_again() -> None:
    gateway = ProjectingGateway(target=80)
    rolemap, uow, _role_id = await _scored_map(gateway)
    [first] = await rolemap.compute_fits(OWNER)

    [again] = await rolemap.compute_fits(OWNER)

    assert len(gateway.shown) == 1 and len(uow.store.fits) == 1
    assert again == first


async def test_a_role_whose_requirements_changed_is_scored_again_alone() -> None:
    gateway = ProjectingGateway(target=80)
    rolemap, _uow, role_id = await _scored_map(gateway)
    other = uuid.uuid4()
    await _store(rolemap, other, [_posting("Platform")], "Platform Engineer")
    await rolemap.compute_fits(OWNER)
    calls = len(gateway.shown)

    # A rebuild read new requirements for one role only.
    await rolemap._store_role(
        OWNER,
        role_id=role_id,
        keys={"k"},
        postings=[_posting("Backend")],
        extraction=_extraction("Backend Engineer", weights=(0.4, 0.95)),
        bar=_BAR,
        bar_reasoning="because",
        model_id="model",
        template_version="v1",
    )
    await rolemap.compute_fits(OWNER)

    assert len(gateway.shown) == calls + 1
    assert "Backend Engineer" in gateway.shown[-1]["role_name"]


async def test_a_new_analysis_scores_every_role_again() -> None:
    gateway = ProjectingGateway(target=80)
    rolemap, _uow, _role_id = await _scored_map(gateway)
    await rolemap.compute_fits(OWNER)

    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [],
        strengths=[StrengthInput("backend", "Backend", "Built more services.", 75, 0.9)],
    )
    await rolemap.compute_fits(OWNER)

    assert len(gateway.shown) == 2


async def test_a_fit_says_what_closing_each_gap_is_worth() -> None:
    rolemap, _uow, _role_id = await _scored_map(ProjectingGateway(target=80))
    [fit] = await rolemap.compute_fits(OWNER)

    lifts = fit.lifts()

    assert lifts.by_dimension["backend"] > 0
    assert len(lifts.by_uncovered) == 1


async def test_fits_are_priced_per_role_the_map_will_hold() -> None:
    """$0.10 a projection: the ten recommended roles a build may make, or the
    ones on the map now."""
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, gateway=ProjectingGateway())
    await _store(rolemap, uuid.uuid4(), [_posting("Backend")], "Backend Engineer")

    priced = await rolemap.estimate_fits(OWNER, recommended=10)
    now = await rolemap.estimate_fits(OWNER)

    assert (priced["roles"], priced["cost_usd"]) == (10, "1.00")
    assert (now["roles"], now["cost_usd"]) == (1, "0.10")


# --- a fit for every opening, worked out locally (Phase 8) -------------------


class TwoDimensionGateway:
    """Projects "backend services" onto backend, wanted at 80, and "data
    pipelines" onto data, wanted at 50. Records how often it was asked."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, owner_id: uuid.UUID, *, task: str, inputs: dict[str, str], **_: Any):
        from advisor.rolemap.service import _Projection

        assert task == "rolemap.fit"
        self.calls += 1
        return _Reply(
            _Projection.model_validate(
                {
                    "mappings": [
                        {"requirement_statement": "backend services", "dimension_id": "backend"},
                        {"requirement_statement": "data pipelines", "dimension_id": "data"},
                    ],
                    "target_scores": [
                        {"dimension_id": "backend", "target": 80},
                        {"dimension_id": "data", "target": 50},
                    ],
                    "reasoning": "Short on services, ahead on data.",
                }
            )
        )


def _opening(title: str, description: str, company: str) -> PostingView:
    return replace(_posting(title, company=company), description=description)


async def _role_with_openings(
    gateway: Any, *, same_company: bool = False
) -> tuple[RoleMapService, FakeRoleMapUnitOfWork, uuid.UUID, PostingView, PostingView]:
    """One role whose two openings ask for different things: one stresses
    backend, where the user falls short, the other data, where they don't."""
    backend = _opening("Platform Engineer", "backend backend backend", "Acme")
    data = _opening("Platform Engineer", "data data data", "Acme" if same_company else "Kestrel")
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, FakeMarket([backend, data]), gateway)
    role_id = uuid.uuid4()
    await rolemap._store_role(
        OWNER,
        role_id=role_id,
        keys={str(backend.id), str(data.id)},
        postings=[backend, data],
        extraction=_RoleExtraction.model_validate(
            {
                "name": "Platform Engineer",
                "requirements": [
                    {"statement": "backend services", "weight": 0.9, "expected_level": "expert"},
                    {"statement": "data pipelines", "weight": 0.5, "expected_level": "senior"},
                ],
            }
        ),
        bar=_BAR,
        bar_reasoning="because",
        model_id="model",
        template_version="v1",
    )
    await rolemap.replace_candidates(
        OWNER,
        uuid.uuid4(),
        [],
        strengths=[
            StrengthInput("backend", "Backend", "Some services.", 60, 0.9),
            StrengthInput("data", "Data", "Many pipelines.", 90, 0.9),
        ],
    )
    return rolemap, uow, role_id, backend, data


@pytest.mark.usefixtures("embedded")
async def test_every_opening_gets_its_own_fit_from_its_roles() -> None:
    gateway = TwoDimensionGateway()
    rolemap, uow, role_id, backend, data = await _role_with_openings(gateway)

    [role_fit] = await rolemap.compute_fits(OWNER)

    # One AI call, for the role; the openings' fits are worked out from it.
    assert gateway.calls == 1
    fits = {f.posting_key: f for f in uow.store.posting_fits.values()}
    assert set(fits) == {str(backend.id), str(data.id)}
    assert all(f.role_id == role_id for f in fits.values())
    assert fits[str(data.id)].score > role_fit.score > fits[str(backend.id)].score


@pytest.mark.usefixtures("embedded")
async def test_working_out_the_openings_fits_is_never_an_ai_call() -> None:
    class NoCalls:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("an opening's fit made an AI call")

    rolemap, uow, _role_id, _backend, _data = await _role_with_openings(TwoDimensionGateway())
    await rolemap.compute_fits(OWNER)
    rolemap._gateway = NoCalls()  # type: ignore[assignment]

    await rolemap._derive_opening_fits(OWNER, await rolemap._strengths(OWNER))

    # Worked out again, and replaced as a set rather than added to.
    assert len(uow.store.posting_fits) == 2


@pytest.mark.usefixtures("embedded")
async def test_a_reused_role_fit_still_has_its_openings_worked_out() -> None:
    gateway = TwoDimensionGateway()
    rolemap, uow, _role_id, _backend, _data = await _role_with_openings(gateway)
    await rolemap.compute_fits(OWNER)
    uow.store.posting_fits.clear()

    await rolemap.compute_fits(OWNER)

    assert gateway.calls == 1 and len(uow.store.posting_fits) == 2


@pytest.mark.usefixtures("embedded")
async def test_a_roles_openings_rank_by_their_own_fit() -> None:
    rolemap, _uow, role_id, backend, data = await _role_with_openings(TwoDimensionGateway())
    before = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)
    await rolemap.compute_fits(OWNER)

    after = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)

    # Before a build works them out, the role's fit, for both.
    assert {m.fit_basis for m in before} == {"role"}
    assert [m.posting_id for m in after] == [data.id, backend.id]
    assert {m.fit_basis for m in after} == {"posting"}
    assert after[0].fit is not None and after[1].fit is not None
    assert after[0].fit > after[1].fit


@pytest.mark.usefixtures("embedded")
async def test_top_matched_keeps_one_opening_per_company_in_a_role_when_asked() -> None:
    rolemap, _uow, role_id, _backend, data = await _role_with_openings(
        TwoDimensionGateway(), same_company=True
    )
    await rolemap.compute_fits(OWNER)

    every = await rolemap.matched_postings(OWNER, limit=None, role_id=role_id)
    top = await rolemap.matched_postings(OWNER, limit=10, role_id=role_id, one_per_company=True)

    assert len(every) == 2
    assert [m.posting_id for m in top] == [data.id]


@pytest.mark.usefixtures("embedded")
async def test_an_openings_fit_is_read_for_its_role_alone() -> None:
    rolemap, _uow, role_id, backend, _data = await _role_with_openings(TwoDimensionGateway())
    assert await rolemap.opening_fit(OWNER, role_id, backend.id) is None
    await rolemap.compute_fits(OWNER)

    fit = await rolemap.opening_fit(OWNER, role_id, backend.id)

    assert fit is not None and fit.posting_key == str(backend.id)
    # The backend opening does not ask for data pipelines: they drop out of it.
    assert [r.statement for r in fit.requirements] == ["backend services"]
    assert await rolemap.opening_fit(OWNER, uuid.uuid4(), backend.id) is None
    assert fit.lifts().by_dimension["backend"] > 0


async def test_no_roles_cost_no_fits() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork(), gateway=ProjectingGateway())

    assert await rolemap.estimate_fits(OWNER, recommended=0) == {
        "cost_usd": "0",
        "roles": 0,
        "rate_is_published": True,
    }
