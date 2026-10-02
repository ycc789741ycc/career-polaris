"""Targets: what a gap plan or a résumé is aimed at (domain decision 26, ADR 0022).

A Target is a value, not a table: one of the user's Roles and optionally one
opening in it, or a posting of the user's own (Phase 8). This module resolves
one through the other components' public surfaces and freezes what it requires
and how the user measures up into a ``TargetSnapshot``, which the plan or
résumé stores.

The role map picks a role and an opening; the Advisor picks a posting of the
user's own. Nothing here spends the user's key: a role is read and scored by
the role-map build, and a posting of the user's own when they add it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.assessment import AssessmentService
from advisor.market import PostingView
from advisor.rolemap import FitView, PostingFitView, RoleMapService, RoleView
from advisor.target.domain import (
    DimensionGap,
    Requirement,
    RequirementBasis,
    TargetError,
    TargetRef,
    TargetSnapshot,
    UncoveredGap,
)
from kernel.clock import utcnow
from kernel.errors import NotFoundError, TargetUnusableError

__all__ = [
    "DimensionGap",
    "TargetError",
    "TargetPreview",
    "TargetRef",
    "TargetService",
    "TargetSnapshot",
    "UncoveredGap",
    "requirements_block",
]


@dataclass(frozen=True, slots=True)
class TargetPreview:
    """What pricing work on a Target needs, resolved without spending anything."""

    label: str
    snapshot: TargetSnapshot
    requirements_text: str


class TargetService:
    def __init__(self, *, assessment: AssessmentService, rolemap: RoleMapService) -> None:
        self._assessment = assessment
        self._rolemap = rolemap

    async def snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        """Freeze the Target: what it requires and the user's fit to it.

        A posting of the user's own is measured against its JD's requirements
        and its own fit. A role is measured against its requirements across its
        openings; an opening narrows the title and company, and is measured
        against its role's (ADR 0022).
        """
        if ref.is_own_posting:
            return await self._own_posting_snapshot(owner_id, ref)
        role = await self._role(owner_id, ref)
        opening = await self._opening(owner_id, role, ref)
        fit = next((f for f in await self._rolemap.fits(owner_id) if f.role_id == role.id), None)
        if fit is None:
            raise TargetUnusableError(
                f"{role.name} has not been scored against your profile yet; "
                "it is scored when the role map is built",
                role_id=str(role.id),
            )
        return await self._freeze(
            owner_id,
            ref,
            role=role,
            title=opening.title if opening else role.name,
            company=opening.company_name if opening else "",
            fit=fit,
            basis=RequirementBasis.ROLE,
        )

    async def _own_posting_snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        posting_id = _uuid(ref.private_job_posting_id or "", ref)
        posting = await self._rolemap.own_posting(owner_id, posting_id)
        fit = await self._rolemap.own_posting_fit(owner_id, posting_id)
        if fit is None:
            raise TargetUnusableError(
                f"{posting.title} has not been scored against your profile yet; "
                "it is scored when you add it",
                private_job_posting_id=ref.private_job_posting_id,
            )
        return await self._freeze(
            owner_id,
            ref,
            role=None,
            title=posting.title,
            company=posting.company_name,
            fit=fit,
            basis=RequirementBasis.POSTING,
        )

    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetPreview:
        """Everything needed to price work on a Target, spending nothing."""
        snapshot = await self.snapshot(owner_id, ref)
        return TargetPreview(
            label=snapshot.label,
            snapshot=snapshot,
            requirements_text=requirements_block(snapshot),
        )

    async def _role(self, owner_id: uuid.UUID, ref: TargetRef) -> RoleView:
        role_id = _uuid(ref.role_id or "", ref)
        for role in await self._rolemap.roles(owner_id):
            if role.id == role_id:
                return role
        raise NotFoundError("that role is no longer on your role map", role_id=ref.role_id)

    async def _opening(
        self, owner_id: uuid.UUID, role: RoleView, ref: TargetRef
    ) -> PostingView | None:
        if ref.job_posting_id is None:
            return None
        posting_id = _uuid(ref.job_posting_id, ref)
        for listed, postings in await self._rolemap.role_postings(owner_id):
            if listed.id == role.id:
                for posting in postings:
                    if posting.id == posting_id:
                        return posting
        raise NotFoundError(
            f"that opening is no longer in {role.name}", job_posting_id=ref.job_posting_id
        )

    async def _freeze(
        self,
        owner_id: uuid.UUID,
        ref: TargetRef,
        *,
        role: RoleView | None,
        title: str,
        company: str,
        fit: FitView | PostingFitView,
        basis: RequirementBasis,
    ) -> TargetSnapshot:
        assessment = await self._assessment.latest(owner_id)
        names = {d.key: d.name for d in assessment.dimensions} if assessment else {}
        lifts = fit.lifts()
        requirements = fit.requirements or (role.requirements if role is not None else ())
        try:
            return TargetSnapshot(
                ref=ref,
                title=title,
                company=company,
                role_id=str(role.id) if role is not None else None,
                role_name=role.name if role is not None else None,
                requirements=tuple(
                    Requirement(r.statement, r.weight, r.expected_level) for r in requirements
                ),
                basis=basis,
                fit_score=fit.score,
                dimensions=tuple(
                    DimensionGap(
                        dimension_key=g["dimension_key"],
                        name=names.get(g["dimension_key"], g["dimension_key"]),
                        user_score=g["user_score"],
                        target_score=g["target_score"],
                        lift=lifts.by_dimension.get(g["dimension_key"], 0),
                    )
                    for g in fit.gaps
                ),
                uncovered=tuple(
                    UncoveredGap(u["statement"], u["weight"], lift)
                    for u, lift in zip(fit.uncovered, lifts.by_uncovered, strict=True)
                ),
                requirement_map=dict(fit.requirement_map),
                taken_at=utcnow(),
            )
        except TargetError as exc:
            raise TargetUnusableError(str(exc), **ref.to_dict()) from exc


def requirements_block(snapshot: TargetSnapshot) -> str:
    return "\n".join(
        f"- {r.statement} (weight {r.weight}, expects {r.expected_level})"
        for r in snapshot.requirements
    )


def _uuid(value: str, ref: TargetRef) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFoundError("target not found", **ref.to_dict()) from exc
