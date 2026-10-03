"""Gap-plan use cases against in-memory storage: requesting, versions, history,
ticking tasks and recording failures, with no database and no model."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from advisor.gapplan import GapPlanService, PlanStatus
from advisor.gapplan.domain import Milestone, Task
from advisor.target import DraftBasis, OutdatedReason, TargetRef
from kernel.errors import NotFoundError
from tests.unit.advisor.gapplan.fakes import FakeGapPlanUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeTarget:
    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> Any:
        named = ref.role_id or ref.private_job_posting_id or ""
        return SimpleNamespace(label=f"Target {named[:8]}")


class OutdatingTarget(FakeTarget):
    """The Target as it stands now hashes to ``digest``; the comparison is the
    real one."""

    def __init__(self, *, digest: str) -> None:
        self.digest = digest

    async def get_outdated_reasons(
        self,
        owner_id: uuid.UUID,
        ref: TargetRef,
        *,
        recorded: DraftBasis | None,
        profile_version: int,
    ) -> tuple[OutdatedReason, ...]:
        if recorded is None:
            return ()
        return recorded.get_outdated_reasons(
            DraftBasis(profile_version=profile_version, target_digest=self.digest)
        )


class VersionedProfile:
    def __init__(self, version: int) -> None:
        self.current = version

    async def version(self, owner_id: uuid.UUID) -> int:
        return self.current


def _service(
    uow: FakeGapPlanUnitOfWork,
    *,
    target: FakeTarget | None = None,
    profile: VersionedProfile | None = None,
) -> GapPlanService:
    return GapPlanService(
        uow,
        target=target or FakeTarget(),  # type: ignore[arg-type]
        profile=profile or VersionedProfile(0),  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        rolemap=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
    )


def _ref() -> TargetRef:
    return TargetRef(str(uuid.uuid4()), str(uuid.uuid4()))


async def _with_tasks(uow: FakeGapPlanUnitOfWork, plan_id: uuid.UUID, *texts: str) -> list[Task]:
    async with uow.for_owner(OWNER) as mine:
        milestone = await mine.milestones.create(
            Milestone(
                id=uuid.uuid4(),
                owner_id=OWNER,
                plan_id=plan_id,
                position=0,
                title="First month",
                time_window="4 weeks",
                outcome="Shipped",
            )
        )
        return [
            await mine.tasks.create(
                Task(
                    id=uuid.uuid4(),
                    owner_id=OWNER,
                    plan_id=plan_id,
                    milestone_id=milestone.id,
                    position=index,
                    text=text,
                    due="week 1",
                    closes=("dim:api",),
                )
            )
            for index, text in enumerate(texts)
        ]


async def test_requesting_again_for_a_target_adds_the_next_version() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    ref, other = _ref(), _ref()

    first = await plans.request(OWNER, ref)
    second = await plans.request(OWNER, ref)
    elsewhere = await plans.request(OWNER, other)

    assert (first.version, second.version, elsewhere.version) == (1, 2, 1)
    assert second.status is PlanStatus.DRAFTING and second.target == ref
    history = (await plans.history(OWNER)).items
    assert [h.id for h in history] == [elsewhere.id, second.id]


async def test_a_role_and_an_opening_in_it_are_versioned_apart() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    role = str(uuid.uuid4())

    for_role = await plans.request(OWNER, TargetRef(role))
    for_opening = await plans.request(OWNER, TargetRef(role, str(uuid.uuid4())))
    for_role_again = await plans.request(OWNER, TargetRef(role))

    assert (for_role.version, for_opening.version, for_role_again.version) == (1, 1, 2)
    assert for_role_again.target == TargetRef(role)


async def test_history_is_paged_after_each_target_keeps_only_its_latest() -> None:
    """Three plans, two Targets: paging the raw rows would count the
    superseded version and show it on page two."""
    plans = _service(FakeGapPlanUnitOfWork())
    ref, other = _ref(), _ref()
    await plans.request(OWNER, ref)
    latest = await plans.request(OWNER, ref)
    elsewhere = await plans.request(OWNER, other)

    first_page = await plans.history(OWNER, page=1, page_size=1)
    second_page = await plans.history(OWNER, page=2, page_size=1)

    assert first_page.total == second_page.total == 2
    assert [h.id for h in first_page.items] == [elsewhere.id]
    assert [h.id for h in second_page.items] == [latest.id]


async def test_a_plan_shows_every_version_and_its_progress() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    ref = _ref()
    first = await plans.request(OWNER, ref)
    second = await plans.request(OWNER, ref)
    done, _open = await _with_tasks(uow, second.id, "Build an API", "Write docs")

    await plans.set_task_done(OWNER, done.id, True)
    view = await plans.get(OWNER, second.id)

    assert [v.version for v in view.versions] == [2, 1]
    assert view.summary.progress == 50
    [milestone] = view.milestones
    assert [(t.text, t.done) for t in milestone.tasks] == [
        ("Build an API", True),
        ("Write docs", False),
    ]
    assert (await plans.get(OWNER, first.id)).summary.progress == 0


async def test_ticking_a_done_task_keeps_when_it_was_done() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    plan = await plans.request(OWNER, _ref())
    [task] = await _with_tasks(uow, plan.id, "Build an API")

    await plans.set_task_done(OWNER, task.id, True)
    first_done = uow.store.tasks[task.id].done_at
    await plans.set_task_done(OWNER, task.id, True)
    assert uow.store.tasks[task.id].done_at == first_done

    await plans.set_task_done(OWNER, task.id, False)
    assert uow.store.tasks[task.id].done_at is None
    with pytest.raises(NotFoundError):
        await plans.set_task_done(OTHER, task.id, True)


async def test_a_failure_is_recorded_on_the_plan_and_drafting_skips_it() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    plan = await plans.request(OWNER, _ref())

    await plans._fail(OWNER, plan.id, code="target_unusable", message="Nothing to plan")
    # A plan no longer drafting is left alone: a retry would spend the key again.
    await plans.draft(OWNER, plan.id)

    view = await plans.get(OWNER, plan.id)
    assert view.summary.status is PlanStatus.FAILED
    assert view.summary.error_code == "target_unusable"
    with pytest.raises(NotFoundError):
        await plans.draft(OTHER, plan.id)


# --- outdated, regenerated only when asked (ADR 0035) -------------------------


def _drafted(uow: FakeGapPlanUnitOfWork, plan_id: uuid.UUID, *, version: int, digest: str) -> None:
    plan = uow.store.plans[plan_id]
    plan.drafted(
        snapshot={},
        label=plan.target_label,
        gaps=(),
        projects=(),
        stepping_stones=(),
        model_id="claude-opus-5",
        template_version="gap_plan/v1",
        profile_version=version,
        target_digest=digest,
        at=plan.created_at,
    )


async def test_a_plan_records_nothing_until_drafted_and_reads_current_while_unchanged() -> None:
    uow = FakeGapPlanUnitOfWork()
    target = OutdatingTarget(digest="d1")
    plans = _service(uow, target=target, profile=VersionedProfile(3))
    plan = await plans.request(OWNER, _ref())
    assert uow.store.plans[plan.id].profile_version is None

    _drafted(uow, plan.id, version=3, digest="d1")
    view = await plans.get(OWNER, plan.id)

    assert not view.is_outdated and view.outdated_by == ()


@pytest.mark.parametrize(
    ("version", "digest", "reasons"),
    [
        (4, "d1", (OutdatedReason.EVIDENCE,)),
        (3, "d2", (OutdatedReason.TARGET,)),
        (4, "d2", (OutdatedReason.EVIDENCE, OutdatedReason.TARGET)),
    ],
)
async def test_the_latest_plan_is_outdated_by_what_moved_on(
    version: int, digest: str, reasons: tuple[OutdatedReason, ...]
) -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow, target=OutdatingTarget(digest=digest), profile=VersionedProfile(version))
    plan = await plans.request(OWNER, _ref())
    _drafted(uow, plan.id, version=3, digest="d1")

    view = await plans.get(OWNER, plan.id)

    assert view.is_outdated and view.outdated_by == reasons


async def test_only_the_targets_latest_ready_plan_is_judged() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow, target=OutdatingTarget(digest="d2"), profile=VersionedProfile(9))
    ref = _ref()
    older = await plans.request(OWNER, ref)
    _drafted(uow, older.id, version=3, digest="d1")
    newer = await plans.request(OWNER, ref)

    # An older version is history; a plan still drafting has read nothing yet.
    assert (await plans.get(OWNER, older.id)).outdated_by == ()
    assert (await plans.get(OWNER, newer.id)).outdated_by == ()


async def test_a_plan_drafted_before_its_basis_was_kept_is_never_outdated() -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow, target=OutdatingTarget(digest="d2"), profile=VersionedProfile(9))
    plan = await plans.request(OWNER, _ref())
    _drafted(uow, plan.id, version=3, digest="d1")
    uow.store.plans[plan.id].profile_version = None
    uow.store.plans[plan.id].target_digest = None

    assert (await plans.get(OWNER, plan.id)).outdated_by == ()
