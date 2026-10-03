"""Skill assessment: the strength report.

One report comes out of here: the radar, this user's dimensions and scores.
The fit between the user and each role belongs to the role map, which scores
it against the scores handed over with the candidates (ADR 0028).

Everything stored is an immutable snapshot recording the profile version, the
model and the prompt template that produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, create_model

from advisor.assessment.domain import (
    MAX_DIMENSIONS,
    MIN_DIMENSIONS,
    AnalysisFinished,
    AnalysisRun,
    AnalysisRunFilter,
    AnalysisRunStatus,
    AssessedScore,
    AssessedScoreFilter,
    AssessmentCompleted,
    AssessmentUnitOfWork,
    DimensionChange,
    DimensionCountError,
    DimensionsChanged,
    LineageKind,
    OwnerAssessment,
    SkillAssessment,
    SkillAssessmentFilter,
    SkillDimension,
    SkillDimensionFilter,
    assert_ids_unique,
    assert_within_bounds,
    derive_lineage,
    dropped_ids,
    profile_confidence,
    thin_evidence,
)
from advisor.assessment.domain import (
    DimensionScore as DimensionValue,
)
from advisor.profile import (
    CitationError,
    CitationHandles,
    ProfileService,
    assert_citations_exist,
    get_evidence_line,
)
from advisor.rolemap import (
    MAX_ROLE_TITLE,
    CandidateInput,
    RoleMapService,
    StrengthInput,
)
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.errors import DimensionCountError as DimensionCountFailure
from kernel.errors import (
    DomainError,
    EvidenceNotOwnedError,
    NotFoundError,
    OutputInvalidError,
    ValidationError,
)
from kernel.logging import get_logger
from kernel.paging import Page

__all__ = [
    "AnalysisRunView",
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
]

log = get_logger(__name__)


# --- AI output schemas -----------------------------------------------------


class _Dimension(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    short_name: str = Field(default="", max_length=32)
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    read: str
    evidence_ids: list[str] = Field(default_factory=list)


class _Candidate(BaseModel):
    """A role the strengths point to, for the role map to search for (ADR 0024)."""

    title: str = Field(min_length=1, max_length=MAX_ROLE_TITLE)
    description: str = Field(min_length=1, max_length=1000)
    dimension_ids: list[str] = Field(min_length=1)


class _Assessment(BaseModel):
    dimensions: list[_Dimension] = Field(min_length=MIN_DIMENSIONS, max_length=MAX_DIMENSIONS)
    candidates: list[_Candidate] = Field(default_factory=list)


def _assessment_schema(candidate_count: int) -> type[_Assessment]:
    """The reply's schema, holding at most ``candidate_count`` candidate roles
    (ADR 0029). A reply with more fails validation in the gateway, which asks
    again, rather than being cut short here."""
    return create_model(
        "_Assessment",
        __base__=_Assessment,
        candidates=(list[_Candidate], Field(default_factory=list, max_length=candidate_count)),
    )


# --- views -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DimensionView:
    key: str
    name: str
    short_name: str
    score: int
    confidence: float
    read: str
    evidence_ids: tuple[str, ...]
    # Below the confidence threshold: the evidence is not enough to be sure,
    # so Strengths points to Sources for more.
    needs_more_evidence: bool


@dataclass(frozen=True, slots=True)
class AssessmentView:
    """``is_out_of_date``: the profile's evidence has changed since this ran.

    Any sync, upload, answer, disconnect or deleted résumé bumps the profile
    version, so an older ``profile_version`` means the scores read facts that
    have since been added, restated or removed.
    """

    id: uuid.UUID
    profile_version: int
    is_out_of_date: bool
    model_id: str
    template_version: str
    created_at: datetime
    dimensions: tuple[DimensionView, ...]
    # How well the evidence backs the scores overall, 0 to 1 (domain decision
    # 28): shown next to Re-analyse on 02 Strengths.
    profile_confidence: float | None


@dataclass(frozen=True, slots=True)
class AnalysisRunView:
    """Whether an analysis is running, and why the last one could not finish."""

    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None

    @property
    def is_running(self) -> bool:
        return self.status == AnalysisRunStatus.RUNNING


class AssessmentService:
    def __init__(
        self,
        uow: AssessmentUnitOfWork,
        *,
        profile: ProfileService,
        rolemap: RoleMapService,
        gateway: AiGateway,
        confidence_threshold: float,
        candidate_count: int,
    ) -> None:
        self._uow = uow
        self._profile = profile
        self._rolemap = rolemap
        self._gateway = gateway
        self._threshold = confidence_threshold
        # How many roles an analysis recommends, all searched for (ADR 0029).
        self._candidate_count = candidate_count
        self._reply = _assessment_schema(candidate_count)

    # -- cost ---------------------------------------------------------------

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        """Priced before anything is spent: the analysis, the role-map build
        that follows it, and the fits scored once that build ends."""
        snapshot = await self._profile.snapshot(owner_id)
        if not snapshot.evidence:
            raise ValidationError(
                "connect a source or upload a resume before analysing", evidence=0
            )
        estimate = await self._gateway.estimate(
            owner_id,
            task="assessment.run",
            template=load_template("skill_assessment", "v4"),
            inputs=_assessment_inputs(
                snapshot,
                CitationHandles(e.id for e in snapshot.evidence),
                existing=(),
                candidate_count=self._candidate_count,
            ),
            untrusted=frozenset({"evidence", "timeline"}),
        )
        # The role map is built after every analysis, so its cost is part of
        # the one confirmation (domain decision 24, ADR 0020), and so are the
        # fits that build is scored with (ADR 0024).
        role_map = await self._rolemap.estimate_cost(owner_id)
        role_map_cost = Decimal(role_map["cost_usd"])
        fits = await self._rolemap.estimate_fits(owner_id, recommended=role_map["max_roles"])
        fits_cost = Decimal(fits["cost_usd"])
        total = estimate.cost_usd + role_map_cost + fits_cost
        return {
            "cost_usd": str(total),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published
            and role_map.get("rate_is_published") is not False
            and fits["rate_is_published"],
            "analysis_cost_usd": str(estimate.cost_usd),
            "role_map_cost_usd": role_map["cost_usd"],
            "fits_cost_usd": fits["cost_usd"],
            "max_roles": role_map["max_roles"],
        }

    # -- the strength report ------------------------------------------------

    async def request_run(self, owner_id: uuid.UUID) -> AnalysisRunView:
        """Record an analysis as running before it is queued (ADR 0006), so the
        page shows it from the moment it is asked for. Whether one may start
        now is ``advisor.activity``'s rule, not this component's."""
        async with self._uow.for_owner(owner_id) as mine:
            requested = await mine.runs.create(
                AnalysisRun.requested(owner_id=owner_id, at=utcnow())
            )
        log.info("assessment.run_requested", run_id=str(requested.id))
        return _run_view(requested)

    async def latest_run(self, owner_id: uuid.UUID) -> AnalysisRunView | None:
        async with self._uow.for_owner(owner_id) as mine:
            newest = await mine.runs.get_list(AnalysisRunFilter(), page_size=1)
        return _run_view(newest[0]) if newest else None

    async def analyse(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> AssessmentView | None:
        """The worker job for one recorded run.

        An expected failure is recorded on the run with its stable code and not
        raised: a retry would spend the key again. Anything else is recorded as
        ``internal`` and re-raised for the log. Returns ``None`` when the run
        has already ended, or ended without a result.
        """
        async with self._uow.for_owner(owner_id) as mine:
            requested = await mine.runs.get(run_id)
        if requested is None:
            raise NotFoundError("analysis run not found", run_id=str(run_id))
        if not requested.is_running:
            return None

        try:
            assessment = await self.run(owner_id)
        except DomainError as exc:
            log.warning("assessment.run_failed", run_id=str(run_id), code=str(exc.code))
            await self.fail_run(owner_id, run_id, code=str(exc.code), message=exc.message)
            return None
        except Exception:
            await self.fail_run(
                owner_id,
                run_id,
                code="internal",
                message="The analysis stopped unexpectedly. Try again in a moment.",
            )
            raise

        async with self._uow.for_owner(owner_id) as mine:
            done = await mine.runs.get(run_id)
            if done is not None and done.is_running:
                done.ready(utcnow())
                await mine.runs.update(done)
                mine.record(
                    AnalysisFinished(
                        owner_id=owner_id, run_id=run_id, status=str(AnalysisRunStatus.READY)
                    )
                )
        return assessment

    async def fail_run(
        self, owner_id: uuid.UUID, run_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        """Close a run without a result. Also how ``advisor.activity`` gives up
        on a run whose worker never came back."""
        async with self._uow.for_owner(owner_id) as mine:
            failed = await mine.runs.get(run_id)
            if failed is None or not failed.is_running:
                return
            failed.failed(code=code, message=message, at=utcnow())
            await mine.runs.update(failed)
            mine.record(
                AnalysisFinished(
                    owner_id=owner_id,
                    run_id=run_id,
                    status=str(AnalysisRunStatus.FAILED),
                    error_code=code,
                )
            )

    async def run(self, owner_id: uuid.UUID) -> AssessmentView:
        snapshot = await self._profile.snapshot(owner_id)
        if not snapshot.evidence:
            raise ValidationError("there is no evidence to analyse yet", evidence=0)

        existing = await self._existing_dimensions(owner_id)
        handles = CitationHandles(e.id for e in snapshot.evidence)
        result = await self._gateway.run(
            owner_id,
            task="assessment.run",
            template=load_template("skill_assessment", "v4"),
            inputs=_assessment_inputs(
                snapshot,
                handles,
                existing=tuple(existing.items()),
                candidate_count=self._candidate_count,
            ),
            output_schema=self._reply,
            untrusted=frozenset({"evidence", "timeline"}),
        )

        owned_evidence = await self._profile.evidence_ids(owner_id)
        dimensions: list[DimensionValue] = []
        for item in result.value.dimensions:
            try:
                evidence_ids = handles.resolve(item.evidence_ids)
                assert_citations_exist(set(evidence_ids), owned_evidence)
            except CitationError as exc:
                # An invented citation is how a fabricated claim gets in.
                raise EvidenceNotOwnedError(
                    "the analysis cited evidence that is not in your profile",
                    invented=sorted(exc.invented),
                ) from exc
            dimensions.append(
                DimensionValue(
                    dimension_id=item.id,
                    name=item.name,
                    short_name=item.short_name or item.name[:24],
                    score=item.score,
                    confidence=item.confidence,
                    read=item.read,
                    evidence_ids=evidence_ids,
                )
            )

        try:
            assert_within_bounds(dimensions)
            assert_ids_unique(dimensions)
        except DimensionCountError as exc:
            raise DimensionCountFailure(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        candidates = _candidates_from(result.value.candidates, {d.dimension_id for d in dimensions})

        assessment_id = await self._store(
            owner_id,
            snapshot_version=snapshot.version,
            dimensions=dimensions,
            existing=existing,
            model_id=result.model_id,
            template_version=result.template_version,
        )
        # The role map searches the market for these on the build that follows
        # (ADR 0024); it owns them, so they are handed over, not stored here,
        # with the scores its local fit estimate weighs them by (ADR 0027) and
        # its fits are scored against (ADR 0028).
        await self._rolemap.replace_candidates(
            owner_id,
            assessment_id,
            candidates,
            strengths=[
                StrengthInput(
                    dimension_key=d.dimension_id,
                    name=d.name,
                    read=d.read,
                    score=d.score,
                    confidence=d.confidence,
                )
                for d in dimensions
            ],
        )

        return await self.latest(owner_id) or _never()

    async def latest(self, owner_id: uuid.UUID) -> AssessmentView | None:
        current = await self._profile.version(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            newest = await mine.assessments.get_list(SkillAssessmentFilter(), page_size=1)
            return (
                await _view(mine, newest[0], current, threshold=self._threshold) if newest else None
            )

    async def history(
        self, owner_id: uuid.UUID, *, page: int = 1, page_size: int | None = None
    ) -> Page[AssessmentView]:
        """Comparing assessments is how progress is shown; stable ids make it work.

        Newest first, paged by the store: one per analysis the user paid for.
        """
        everything = SkillAssessmentFilter()
        current = await self._profile.version(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.assessments.get_list(everything, page=page, page_size=page_size)
            total = await mine.assessments.get_count(everything)
            views = tuple(
                [
                    await _view(mine, assessment, current, threshold=self._threshold)
                    for assessment in found
                ]
            )
        return Page(views, page, page_size, total)

    # -- internals ----------------------------------------------------------

    async def _existing_dimensions(self, owner_id: uuid.UUID) -> dict[str, str]:
        async with self._uow.for_owner(owner_id) as mine:
            known = await mine.dimensions.get_list(SkillDimensionFilter())
        return {d.key: d.name for d in known}

    async def _store(
        self,
        owner_id: uuid.UUID,
        *,
        snapshot_version: int,
        dimensions: list[DimensionValue],
        existing: dict[str, str],
        model_id: str,
        template_version: str,
    ) -> uuid.UUID:
        lineage = derive_lineage(existing, dimensions)
        dropped = dropped_ids(existing, dimensions)

        async with self._uow.for_owner(owner_id) as mine:
            assessment = await mine.assessments.create(
                SkillAssessment(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    profile_version=snapshot_version,
                    model_id=model_id,
                    template_version=template_version,
                )
            )
            by_key = {d.key: d for d in await mine.dimensions.get_list(SkillDimensionFilter())}

            for dimension in dimensions:
                known = by_key.get(dimension.dimension_id)
                if known is None:
                    await mine.dimensions.create(
                        SkillDimension(
                            id=uuid.uuid4(),
                            owner_id=owner_id,
                            key=dimension.dimension_id,
                            name=dimension.name,
                            short_name=dimension.short_name,
                        )
                    )
                else:
                    known.rename(name=dimension.name, short_name=dimension.short_name)
                    await mine.dimensions.update(known)

                await mine.scores.create(
                    AssessedScore(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        dimension_key=dimension.dimension_id,
                        score=dimension.score,
                        confidence=dimension.confidence,
                        read=dimension.read,
                        evidence_ids=tuple(dimension.evidence_ids),
                    )
                )

            for entry in lineage:
                await mine.changes.create(
                    DimensionChange(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        kind=entry.kind,
                        dimension_key=entry.dimension_id,
                        from_keys=tuple(entry.from_ids),
                        previous_name=entry.previous_name,
                    )
                )

            # A dimension that stops appearing is retired with a record, never
            # silently orphaned — old radar points still resolve.
            for key in dropped:
                gone = by_key.get(key)
                if gone is not None:
                    gone.retire(utcnow())
                    await mine.dimensions.update(gone)
                await mine.changes.create(
                    DimensionChange(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        kind=LineageKind.MERGED,
                        dimension_key=key,
                        previous_name=existing.get(key),
                    )
                )

            mine.record(
                AssessmentCompleted(
                    owner_id=owner_id,
                    assessment_id=assessment.id,
                    dimensions=len(dimensions),
                    model_id=model_id,
                )
            )
            if lineage or dropped:
                mine.record(
                    DimensionsChanged(
                        owner_id=owner_id, added_or_renamed=len(lineage), retired=len(dropped)
                    )
                )
            return assessment.id


async def _view(
    mine: OwnerAssessment,
    assessment: SkillAssessment,
    profile_version: int,
    *,
    threshold: float,
) -> AssessmentView:
    """An assessment with its scores, named by the user's dimensions.

    ``profile_version`` is the profile's version now, to compare against the
    one the assessment read. ``threshold`` is the confidence below which a
    score needs more evidence, which Strengths points to Sources for.
    """
    scores = await mine.scores.get_list(AssessedScoreFilter(assessment_id=assessment.id))
    thin = {s.dimension_key for s in thin_evidence(scores, threshold=threshold)}
    names = {
        d.key: (d.name, d.short_name)
        for d in await mine.dimensions.get_list(SkillDimensionFilter())
    }
    # Set by the database when the assessment was stored.
    assert assessment.created_at is not None, "a stored assessment has a creation time"
    return AssessmentView(
        id=assessment.id,
        profile_version=assessment.profile_version,
        is_out_of_date=assessment.profile_version < profile_version,
        model_id=assessment.model_id,
        template_version=assessment.template_version,
        created_at=assessment.created_at,
        dimensions=tuple(
            DimensionView(
                key=s.dimension_key,
                name=names.get(s.dimension_key, (s.dimension_key, ""))[0],
                short_name=names.get(s.dimension_key, ("", ""))[1],
                score=s.score,
                confidence=s.confidence,
                read=s.read,
                evidence_ids=s.evidence_ids,
                needs_more_evidence=s.dimension_key in thin,
            )
            for s in sorted(scores, key=lambda s: s.dimension_key)
        ),
        profile_confidence=profile_confidence(scores),
    )


def _assessment_inputs(
    snapshot: Any,
    handles: CitationHandles,
    *,
    existing: tuple[tuple[str, str], ...],
    candidate_count: int,
) -> dict[str, str]:
    return {
        "timeline": _timeline_block(snapshot),
        "evidence": _evidence_block(snapshot, handles),
        "existing_dimensions": (
            "\n".join(f"- {key}: {name}" for key, name in existing) or "(none yet)"
        ),
        "candidate_count": str(candidate_count),
    }


def _timeline_block(snapshot: Any) -> str:
    if not snapshot.positions:
        return "(no positions recorded)"
    lines = [
        f"- {p.title} at {p.company}, {p.started_on} to {p.ended_on or 'present'}"
        for p in snapshot.positions
    ]
    lines.append(
        f"Total experience, overlaps counted once: {snapshot.total_experience_months} months"
    )
    return "\n".join(lines)


def _evidence_block(snapshot: Any, handles: CitationHandles) -> str:
    return "\n".join(get_evidence_line(e, handles.handle(e.id)) for e in snapshot.evidence)


def _run_view(run: AnalysisRun) -> AnalysisRunView:
    return AnalysisRunView(
        id=run.id,
        status=str(run.status),
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_code=run.error_code,
        error_message=run.error_message,
    )


def _never() -> AssessmentView:
    raise NotFoundError("the assessment disappeared immediately after being written")


def _candidates_from(candidates: list[_Candidate], dimension_ids: set[str]) -> list[CandidateInput]:
    """The analysis's candidate roles, each resting on dimensions it produced.

    A candidate citing a dimension that is not in the same reply is the model
    inventing a basis for it, so the whole reply is rejected, as an invented
    evidence id is.
    """
    handed_over: list[CandidateInput] = []
    for candidate in candidates:
        invented = sorted(set(candidate.dimension_ids) - dimension_ids)
        if invented:
            raise OutputInvalidError(
                "the analysis recommended a role on a dimension it did not produce",
                invented=invented,
            )
        handed_over.append(
            CandidateInput(
                title=candidate.title.strip(),
                description=candidate.description.strip(),
                dimension_keys=tuple(dict.fromkeys(candidate.dimension_ids)),
            )
        )
    return handed_over
