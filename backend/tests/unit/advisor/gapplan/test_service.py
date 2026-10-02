"""Gap-plan use cases against in-memory storage: requesting, versions, history,
ticking tasks and recording failures, with no database and no model."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from advisor.gapplan import GapPlanService, PlanStatus
from advisor.gapplan.domain import Milestone, Task
from advisor.target import TargetRef
from kernel.errors import NotFoundError
from tests.unit.advisor.gapplan.fakes import FakeGapPlanUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeTarget:
    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> Any:
        named = ref.role_id or ref.private_job_posting_id or ""
        return SimpleNamespace(label=f"Target {named[:8]}")


def _service(uow: FakeGapPlanUnitOfWork) -> GapPlanService:
    return GapPlanService(
        uow,
        target=FakeTarget(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
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


# --- after Fill the gap (ADR 0023) -------------------------------------------


async def test_regenerating_a_target_with_no_plan_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = _service(FakeGapPlanUnitOfWork())

    assert await plans.regenerate(OWNER, _ref()) is None


async def test_regenerating_drafts_the_targets_next_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeGapPlanUnitOfWork()
    plans = _service(uow)
    ref = _ref()
    await plans.request(OWNER, ref)
    drafted: list[uuid.UUID] = []

    async def draft(owner_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        drafted.append(plan_id)

    monkeypatch.setattr(plans, "draft", draft)

    regenerated = await plans.regenerate(OWNER, ref)

    assert regenerated is not None and drafted == [regenerated]
    latest = await plans.latest_for(OWNER, ref)
    assert latest is not None and (latest.id, latest.version) == (regenerated, 2)
