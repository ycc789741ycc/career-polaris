"""Role-map use cases against in-memory storage: what they store and announce,
with no database, no model and no clustering."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from advisor.market import PostingView, SalaryRange, Visibility
from advisor.rolemap import RoleMapService
from advisor.rolemap.domain import (
    DEFAULT_ROLE_COUNT,
    BarBasis,
    HiringBar,
    RoleChange,
    RoleCountChanged,
    RoleLineage,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    reconcile,
)
from advisor.rolemap.service import _RoleExtraction
from kernel.errors import ValidationError
from tests.unit.advisor.rolemap.fakes import FakeRoleMapUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeMarket:
    def __init__(
        self, postings: list[PostingView] | None = None, markets: list[str] | None = None
    ) -> None:
        self.postings = postings or []
        self.chosen = markets or []

    async def target_locations(self, owner_id: uuid.UUID) -> list[str]:
        return self.chosen

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        return self.postings


def _service(uow: FakeRoleMapUnitOfWork, market: FakeMarket | None = None) -> RoleMapService:
    return RoleMapService(
        uow,
        market=market or FakeMarket(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        embedding_model="test-model",
    )


def _posting(title: str) -> PostingView:
    return PostingView(
        id=uuid.uuid4(),
        company_name="Acme",
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


async def test_the_role_count_defaults_and_a_change_is_announced_once() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)

    assert await rolemap.role_count(OWNER) == DEFAULT_ROLE_COUNT
    await rolemap.set_role_count(OWNER, 5)
    await rolemap.set_role_count(OWNER, 5)

    assert await rolemap.role_count(OWNER) == 5
    assert await rolemap.role_count(OTHER) == DEFAULT_ROLE_COUNT
    assert uow.store.events == [
        RoleCountChanged(owner_id=OWNER, previous=DEFAULT_ROLE_COUNT, current=5)
    ]


async def test_a_role_count_outside_the_bounds_is_refused() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeRoleMapUnitOfWork()).set_role_count(OWNER, 0)


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
