"""Gap plan's wire shapes: a route to a Target, and working through it."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from advisor.gapplan import GapView, MilestoneView, PlanSummaryView, PlanView
from api.schemas.common import (
    ApiModel,
    EvidenceCitation,
    JobError,
    Page,
    RequestModel,
    Timestamp,
)
from api.schemas.target import TargetFields, TargetRefBody

PlanStatusName = Literal["drafting", "ready", "failed"]


class TargetRequest(TargetFields):
    """A role and optionally one opening in it (ADR 0022), or a posting of the
    user's own."""


class TaskDoneRequest(RequestModel):
    done: bool = Field(description="Whether the task is finished.")


class PlanSummary(ApiModel):
    id: uuid.UUID
    target: TargetRefBody
    label: str
    version: int
    # drafting -> ready | failed. A failure carries the error's stable code.
    status: PlanStatusName
    error: JobError | None
    model_id: str | None
    created_at: Timestamp
    drafted_at: Timestamp | None
    progress: int

    @classmethod
    def from_view(cls, plan: PlanSummaryView) -> PlanSummary:
        return cls(
            id=plan.id,
            target=TargetRefBody.from_ref(plan.target),
            label=plan.label,
            version=plan.version,
            status=str(plan.status),
            error=JobError.of(plan.error_code, plan.error_message),
            model_id=plan.model_id,
            created_at=plan.created_at,
            drafted_at=plan.drafted_at,
            progress=plan.progress,
        )


class PlanRequirement(ApiModel):
    statement: str
    expected_level: str


class PlanSnapshot(ApiModel):
    """The Target as it was when the plan was drafted."""

    title: str
    company: str
    role_name: str | None
    fit: int | None
    # "role": the Role's requirements; "opening": the Role's, as the opening
    # weighs them; "posting": read from a posting of the user's own's JD.
    basis: Literal["role", "opening", "posting"]
    requirements: list[PlanRequirement]
    taken_at: Timestamp


class PlanGap(ApiModel):
    key: str
    kind: Literal["dimension", "uncovered"]
    name: str
    user_score: int | None
    target_score: int | None
    lift: int
    why: str
    evidence: list[EvidenceCitation]

    @classmethod
    def from_view(cls, gap: GapView) -> PlanGap:
        return cls(
            key=gap.key,
            kind=gap.kind,
            name=gap.name,
            user_score=gap.user_score,
            target_score=gap.target_score,
            lift=gap.lift,
            why=gap.why,
            evidence=[
                EvidenceCitation(id=e.id, reference=e.reference, fact=e.fact) for e in gap.evidence
            ],
        )


class PlanTask(ApiModel):
    id: uuid.UUID
    text: str
    due: str
    closes: list[str]
    done: bool
    # Finished as a matching task in another plan; it counts here too.
    done_elsewhere: bool


class Milestone(ApiModel):
    id: uuid.UUID
    title: str
    window: str
    outcome: str
    tasks: list[PlanTask]

    @classmethod
    def from_view(cls, milestone: MilestoneView) -> Milestone:
        return cls(
            id=milestone.id,
            title=milestone.title,
            window=milestone.window,
            outcome=milestone.outcome,
            tasks=[
                PlanTask(
                    id=t.id,
                    text=t.text,
                    due=t.due,
                    closes=list(t.closes),
                    done=t.done,
                    done_elsewhere=t.done_elsewhere,
                )
                for t in milestone.tasks
            ],
        )


class PlanProject(ApiModel):
    name: str
    note: str
    closes: list[str]


class SteppingStone(ApiModel):
    role_id: str
    name: str
    fit: int
    openings: int


class Plan(PlanSummary):
    template_version: str | None
    snapshot: PlanSnapshot | None
    gaps: list[PlanGap]
    milestones: list[Milestone]
    projects: list[PlanProject]
    stepping_stones: list[SteppingStone]
    versions: list[PlanSummary]

    @classmethod
    def from_plan(cls, plan: PlanView) -> Plan:
        snapshot = plan.snapshot
        return cls(
            **PlanSummary.from_view(plan.summary).model_dump(),
            template_version=plan.template_version,
            snapshot=(
                PlanSnapshot(
                    title=snapshot.title,
                    company=snapshot.company,
                    role_name=snapshot.role_name,
                    fit=snapshot.fit_score,
                    basis=str(snapshot.basis),
                    requirements=[
                        PlanRequirement(statement=r.statement, expected_level=r.expected_level)
                        for r in snapshot.requirements
                    ],
                    taken_at=snapshot.taken_at,
                )
                if snapshot
                else None
            ),
            gaps=[PlanGap.from_view(g) for g in plan.gaps],
            milestones=[Milestone.from_view(m) for m in plan.milestones],
            # Stored as the JSON they were drafted as; validated on the way out.
            projects=[PlanProject.model_validate(p) for p in plan.projects],
            stepping_stones=[
                SteppingStone(role_id=s.role_id, name=s.name, fit=s.fit, openings=s.openings)
                for s in plan.stepping_stones
            ],
            versions=[PlanSummary.from_view(v) for v in plan.versions],
        )


class PlanSummaryPage(Page[PlanSummary]):
    pass
