"""Targets: what a gap plan or a résumé is aimed at (domain decision 26, ADR 0022).

A Target is a value, not a table: one of the user's Roles, recommended or
custom, and optionally one opening in it. This module resolves one through the
other components' public surfaces and freezes what it requires and how the user
measures up into a ``TargetSnapshot``, which the plan or résumé stores.

The role map is the only picker: the SPA carries the role, and the opening when
one was picked, to the Advisor. Nothing here spends the user's key — a role is
read and scored by the role-map build, a custom role's JD included.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.assessment import AssessmentService
from advisor.market import PostingView
from advisor.rolemap import FitView, RoleMapService, RoleView
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
        """Freeze the Target: its role's requirements and the user's fit to them.

        The requirements are the most specific the Target has: a custom role's
        private JD, else the role's across its openings. An opening narrows the
        title and company; per-opening requirements are not read yet, so an
        opening in a role is measured against the role's (ADR 0022).
        """
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
            company=opening.company_name if opening else role.company_name or "",
            fit=fit,
            basis=(
                RequirementBasis.POSTING
                if role.is_custom and role.private_posting_id is not None
                else RequirementBasis.ROLE
            ),
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
        role_id = _uuid(ref.role_id, ref)
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
        role: RoleView,
        title: str,
        company: str,
        fit: FitView,
        basis: RequirementBasis,
    ) -> TargetSnapshot:
        assessment = await self._assessment.latest(owner_id)
        names = {d.key: d.name for d in assessment.dimensions} if assessment else {}
        lifts = fit.lifts()
        requirements = fit.requirements or role.requirements
        try:
            return TargetSnapshot(
                ref=ref,
                title=title,
                company=company,
                role_id=str(role.id),
                role_name=role.name,
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
            raise TargetUnusableError(str(exc), role_id=ref.role_id) from exc


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
