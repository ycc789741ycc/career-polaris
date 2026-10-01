"""Role-map use cases against in-memory storage: what they store and announce,
with no database, no model and no embedding model."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from advisor.market import PostingView, SalaryRange, Visibility
from advisor.rolemap import CANDIDATE_ROLE_COUNT, CandidateInput, RoleMapService
from advisor.rolemap import service as rolemap_service
from advisor.rolemap.domain import (
    BarBasis,
    CustomRoleAdded,
    HiringBar,
    RoleCandidatesReplaced,
    RoleChange,
    RoleLineage,
    RoleMapBuildFinished,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    reconcile,
)
from advisor.rolemap.service import _RoleExtraction
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.rolemap.fakes import FakeRoleMapUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeMarket:
    def __init__(
        self,
        postings: list[PostingView] | None = None,
        markets: list[str] | None = None,
        pasted: list[PostingView] | None = None,
    ) -> None:
        self.postings = postings or []
        self.chosen = markets or []
        self.pasted = {p.id: p for p in pasted or []}

    async def private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> PostingView:
        if posting_id not in self.pasted:
            raise NotFoundError("job description not found")
        return self.pasted[posting_id]

    async def target_locations(self, owner_id: uuid.UUID) -> list[str]:
        return self.chosen

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        return self.postings

    async def scope_with_vectors(
        self, owner_id: uuid.UUID, model_name: str
    ) -> list[tuple[str, PostingView, list[float] | None]]:
        # None: nothing embedded yet, so the service embeds them itself.
        return [(str(p.id), p, None) for p in self.postings]


def _service(
    uow: FakeRoleMapUnitOfWork, market: FakeMarket | None = None, gateway: Any = None
) -> RoleMapService:
    return RoleMapService(
        uow,
        market=market or FakeMarket(),  # type: ignore[arg-type]
        gateway=gateway,
        embedding_model="test-model",
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


# --- builds (ADR 0006, ADR 0018) -------------------------------------------


async def test_a_build_asked_for_now_runs_and_is_queued_once() -> None:
    service = _service(FakeRoleMapUnitOfWork())

    first = await service.request_build(OWNER, wait=False)
    again = await service.request_build(OWNER, wait=False)

    assert first.should_queue and first.build.status == "running"
    assert not again.should_queue and again.build.id == first.build.id


async def test_a_build_asked_for_during_an_analysis_waits_until_it_is_started() -> None:
    service = _service(FakeRoleMapUnitOfWork())

    waiting = await service.request_build(OWNER, wait=True)
    assert not waiting.should_queue and waiting.build.status == "waiting"
    assert (await service.request_build(OWNER, wait=True)).build.id == waiting.build.id

    started = await service.start_waiting(OWNER)

    assert started is not None and started.id == waiting.build.id
    assert started.status == "running" and started.started_at is not None
    assert await service.start_waiting(OWNER) is None


async def test_asking_again_once_nothing_is_running_starts_the_waiting_build() -> None:
    service = _service(FakeRoleMapUnitOfWork())
    waiting = await service.request_build(OWNER, wait=True)

    now = await service.request_build(OWNER, wait=False)

    assert now.should_queue and now.build.id == waiting.build.id
    assert now.build.status == "running"


async def test_a_finished_build_is_ready_and_the_next_request_is_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(FakeRoleMapUnitOfWork())
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID) -> list[Any]:
        return []

    monkeypatch.setattr(service, "recluster", recluster)

    assert await service.build(OWNER, requested.build.id) == []

    latest = await service.latest_build(OWNER)
    assert latest is not None and latest.status == "ready" and latest.finished_at is not None
    assert (await service.request_build(OWNER, wait=False)).build.id != requested.build.id


async def test_a_failed_build_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(FakeRoleMapUnitOfWork())
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID) -> list[Any]:
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

    async def recluster(owner_id: uuid.UUID) -> list[Any]:
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


# --- custom roles (ADR 0021) --------------------------------------------------


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


def _jd(title: str = "Staff Engineer") -> PostingView:
    return PostingView(
        id=uuid.uuid4(),
        company_name="Northwind",
        title=title,
        location=None,
        url=None,
        description="Own the ledger. Lead incident response.",
        visibility=Visibility.PRIVATE,
        salary=None,
    )


async def test_adding_a_custom_role_announces_its_company() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)

    role = await rolemap.add_custom_role(
        OWNER, title=" Staff Engineer ", company_name=" Northwind ", private_posting_id=None
    )

    assert (role.name, role.company_name, role.is_custom) == ("Staff Engineer", "Northwind", True)
    assert uow.store.events == [
        CustomRoleAdded(owner_id=OWNER, role_id=role.id, company_name="Northwind")
    ]


async def test_a_custom_role_needs_a_title() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeRoleMapUnitOfWork()).add_custom_role(
            OWNER, title="  ", company_name=None, private_posting_id=None
        )


async def test_only_a_custom_role_can_be_removed_and_it_is_retired_not_deleted() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    custom = await rolemap.add_custom_role(
        OWNER, title="Staff Engineer", company_name=None, private_posting_id=None
    )
    recommended = uuid.uuid4()
    await _store(rolemap, recommended, [_posting("Backend")], "Backend")

    await rolemap.remove_custom_role(OWNER, custom.id)
    await rolemap.remove_custom_role(OWNER, custom.id)

    assert [r.id for r in await rolemap.roles(OWNER)] == [recommended]
    assert uow.store.roles[custom.id].retired_at is not None
    with pytest.raises(NotFoundError):
        await rolemap.remove_custom_role(OWNER, recommended)


async def test_a_custom_role_takes_in_postings_by_title_words_at_its_company() -> None:
    uow = FakeRoleMapUnitOfWork()
    staff = _posting("Backend Engineer, Staff", company="Northwind Pay")
    elsewhere = _posting("Staff Backend Engineer", company="Acme")
    other = _posting("Staff Designer", company="Northwind Pay")
    gateway = ScriptedGateway()
    rolemap = _service(uow, FakeMarket([staff, elsewhere, other]), gateway)
    role = await rolemap.add_custom_role(
        OWNER, title="Staff Backend", company_name="Northwind", private_posting_id=None
    )

    [placed] = await rolemap.recluster(OWNER)

    assert placed.id == role.id and placed.name == "Staff Backend"
    assert placed.opening_count == 1 and placed.requirements
    assert "Backend Engineer, Staff" in gateway.shown[0]
    assert "Acme" not in gateway.shown[0]


async def test_a_custom_roles_requirements_come_from_its_jd_when_it_has_one() -> None:
    uow = FakeRoleMapUnitOfWork()
    jd = _jd()
    gateway = ScriptedGateway()
    rolemap = _service(uow, FakeMarket([_posting("Staff Engineer")], pasted=[jd]), gateway)
    await rolemap.add_custom_role(
        OWNER, title="Staff Engineer", company_name=None, private_posting_id=jd.id
    )

    [placed] = await rolemap.recluster(OWNER)

    assert placed.opening_count == 1
    assert all("Own the ledger" in shown for shown in gateway.shown)


async def test_an_unchanged_custom_role_costs_nothing_on_the_next_build() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = ScriptedGateway()
    rolemap = _service(uow, FakeMarket([_posting("Staff Engineer")]), gateway)
    await rolemap.add_custom_role(
        OWNER, title="Staff Engineer", company_name=None, private_posting_id=None
    )
    await rolemap.recluster(OWNER)
    calls = len(gateway.shown)

    await rolemap.recluster(OWNER)

    assert len(gateway.shown) == calls == 2


async def test_a_custom_role_with_nothing_to_read_stays_on_the_map_unscored() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = ScriptedGateway()
    rolemap = _service(uow, FakeMarket([_posting("Designer")]), gateway)
    await rolemap.add_custom_role(
        OWNER, title="Staff Engineer", company_name=None, private_posting_id=None
    )

    [placed] = await rolemap.recluster(OWNER)

    assert (placed.opening_count, placed.requirements) == (0, ())
    assert gateway.shown == []


async def test_reconciliation_never_retires_a_custom_role() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    custom = await rolemap.add_custom_role(
        OWNER, title="Staff Engineer", company_name=None, private_posting_id=None
    )
    await _store(rolemap, custom.id, [_posting("Staff Engineer")], "Staff Engineer")

    assert await rolemap._previous_members(OWNER) == {}


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


async def test_new_candidates_are_announced_by_title_for_the_market_to_search() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)

    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("First", "a"), _candidate("Second", "b")]
    )

    assert uow.store.events == [RoleCandidatesReplaced(OWNER, ("First", "Second"))]


async def test_an_analysis_that_recommends_nothing_asks_for_no_search() -> None:
    uow = FakeRoleMapUnitOfWork()

    await _service(uow).replace_candidates(OWNER, uuid.uuid4(), [])

    assert uow.store.events == []


async def test_an_analysis_recommends_no_more_than_twenty_roles() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())
    too_many = [_candidate(f"Role {i}", "work") for i in range(CANDIDATE_ROLE_COUNT + 1)]

    with pytest.raises(ValidationError, match="at most"):
        await rolemap.replace_candidates(OWNER, uuid.uuid4(), too_many)


async def test_candidates_are_per_user() -> None:
    rolemap = _service(FakeRoleMapUnitOfWork())
    await rolemap.replace_candidates(OWNER, uuid.uuid4(), [_candidate("Mine", "work")])

    assert await rolemap.candidates(OTHER) == []


@pytest.mark.usefixtures("embedded")
async def test_without_candidates_a_build_names_no_recommended_role() -> None:
    """No analysis has succeeded, so nothing the user priced exists to spend on."""
    gateway = ScriptedGateway()
    rolemap = _service(FakeRoleMapUnitOfWork(), _market(), gateway)

    assert await rolemap.recluster(OWNER) == []
    assert gateway.shown == []


@pytest.mark.usefixtures("embedded")
async def test_a_candidate_the_market_has_becomes_a_role_named_from_its_openings() -> None:
    uow = FakeRoleMapUnitOfWork()
    gateway = ScriptedGateway()
    rolemap = _service(uow, _market(backend=3, designer=1), gateway)
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )

    [role] = await rolemap.recluster(OWNER)

    assert role.name == "Whatever the model calls it" and role.opening_count == 3
    assert "Designer" not in gateway.shown[0]
    [candidate] = await rolemap.candidates(OWNER)
    assert (candidate.role_id, candidate.opening_count) == (role.id, 3)


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

    [role] = await rolemap.recluster(OWNER)

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
    [first] = await rolemap.recluster(OWNER)
    calls = len(gateway.shown)

    [again] = await rolemap.recluster(OWNER)

    assert again.id == first.id and len(gateway.shown) == calls


@pytest.mark.usefixtures("embedded")
async def test_a_new_analysiss_candidates_retire_the_roles_they_no_longer_include() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow, _market(backend=3, designer=3), ScriptedGateway())
    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Backend Engineer", "Backend services.")]
    )
    [backend] = await rolemap.recluster(OWNER)

    await rolemap.replace_candidates(
        OWNER, uuid.uuid4(), [_candidate("Designer", "Designer work.")]
    )
    [designer] = await rolemap.recluster(OWNER)

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
    [role] = await rolemap.recluster(OWNER)
    market.postings = []

    assert [r.id for r in await rolemap.recluster(OWNER)] == [role.id]
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

    await rolemap.recluster(OWNER)

    [candidate] = await rolemap.candidates(OWNER)
    assert (candidate.title, candidate.role_id) == ("Designer", None)


# --- fits, scored once per build (ADR 0024) ---------------------------------


async def test_a_finished_build_announces_itself_for_its_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeRoleMapUnitOfWork()
    service = _service(uow)
    requested = await service.request_build(OWNER, wait=False)

    async def recluster(owner_id: uuid.UUID) -> list[Any]:
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
