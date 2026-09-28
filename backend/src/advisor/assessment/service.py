"""Skill assessment, follow-up questions and fit.

Two reports come out of here: the radar (this user's dimensions and scores)
and the bubble sizes (fit between this user and each role).

Everything stored is an immutable snapshot recording the profile version, the
model and the prompt template that produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from advisor.assessment.domain import (
    DEFAULT_MATCHES,
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
    ClosingLifts,
    DimensionChange,
    DimensionCountError,
    DimensionsChanged,
    FitResult,
    FollowUpQuestion,
    FollowUpQuestionFilter,
    LineageKind,
    MatchCandidate,
    OwnerAssessment,
    QuestionAnswered,
    QuestionRound,
    QuestionRoundFilter,
    QuestionRoundStatus,
    QuestionRoundTrigger,
    QuestionsRaised,
    RoleFit,
    RoleFitFilter,
    RoleFitsComputed,
    SkillAssessment,
    SkillAssessmentFilter,
    SkillDimension,
    SkillDimensionFilter,
    SkillGap,
    TargetScore,
    UncoveredRequirement,
    assert_ids_unique,
    assert_within_bounds,
    closing_lifts,
    derive_lineage,
    dropped_ids,
    evaluate,
    needs_follow_up,
    rank_matches,
)
from advisor.assessment.domain import (
    DimensionScore as DimensionValue,
)
from advisor.market import MarketService, PostingView, SalaryRange, Visibility
from advisor.profile import (
    CitationError,
    CitationHandles,
    ProfileService,
    assert_citations_exist,
)
from advisor.rolemap import RequirementView, RoleMapService, RoleView
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.errors import DimensionCountError as DimensionCountFailure
from kernel.errors import DomainError, EvidenceNotOwnedError, NotFoundError, ValidationError
from kernel.logging import get_logger
from kernel.paging import Page, paginate

__all__ = [
    "AnalysisRunView",
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
    "FitView",
    "MatchedPostingView",
    "QuestionRoundView",
    "QuestionView",
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


class _Assessment(BaseModel):
    dimensions: list[_Dimension] = Field(min_length=MIN_DIMENSIONS, max_length=MAX_DIMENSIONS)


class _Question(BaseModel):
    dimension_id: str
    text: str
    why: str
    options: list[str] = Field(min_length=2, max_length=4)


class _Questions(BaseModel):
    questions: list[_Question] = Field(max_length=5)


class _Mapping(BaseModel):
    requirement_statement: str
    dimension_id: str | None = None


class _Target(BaseModel):
    dimension_id: str
    target: int = Field(ge=0, le=100)


class _PostingRequirement(BaseModel):
    statement: str = Field(min_length=1, max_length=400)
    weight: float = Field(ge=0.0, le=1.0)
    expected_level: str = Field(pattern="^(familiar|proficient|advanced|expert)$")


class _PostingRequirements(BaseModel):
    requirements: list[_PostingRequirement] = Field(min_length=3, max_length=12)


class _Projection(BaseModel):
    mappings: list[_Mapping]
    target_scores: list[_Target]
    reasoning: str


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
    # which is also what makes follow-up questions ask about it.
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


@dataclass(frozen=True, slots=True)
class QuestionView:
    id: uuid.UUID
    dimension_key: str
    text: str
    why: str
    options: tuple[str, ...]
    answer: str | None


@dataclass(frozen=True, slots=True)
class QuestionRoundView:
    """Whether questions are being generated, and why they could not be."""

    id: uuid.UUID
    trigger: str
    status: str
    question_count: int
    created_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


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


@dataclass(frozen=True, slots=True)
class FitView:
    role_id: uuid.UUID | None
    private_posting_id: uuid.UUID | None
    score: int
    reasoning: str
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    model_id: str
    created_at: datetime
    assessment_id: uuid.UUID | None = None
    target_profile: dict[str, int] = field(default_factory=dict)
    # What the fit was projected from; empty for fits taken before these were
    # recorded.
    requirements: tuple[RequirementView, ...] = ()
    requirement_map: dict[str, str | None] = field(default_factory=dict)

    def lifts(self) -> ClosingLifts:
        """Fit points each gap is worth, by the fit's own arithmetic."""
        return closing_lifts(
            gaps=[
                SkillGap(g["dimension_key"], g["user_score"], g["target_score"]) for g in self.gaps
            ],
            uncovered=[UncoveredRequirement(u["statement"], u["weight"]) for u in self.uncovered],
        )


@dataclass(frozen=True, slots=True)
class MatchedPostingView:
    """One opening inside one of the user's roles, ranked by that role's fit."""

    posting_id: uuid.UUID
    role_id: uuid.UUID
    role_name: str
    title: str
    company_name: str
    location: str | None
    url: str | None
    salary: SalaryRange | None
    fit: int | None
    subscription_id: uuid.UUID | None
    # The crawl source kind (atsBoard, jsonLd, publicApi); never a site that
    # forbids crawling (domain decision 6).
    source_kind: str | None = None


class AssessmentService:
    def __init__(
        self,
        uow: AssessmentUnitOfWork,
        *,
        profile: ProfileService,
        rolemap: RoleMapService,
        market: MarketService,
        gateway: AiGateway,
        confidence_threshold: float,
    ) -> None:
        self._uow = uow
        self._profile = profile
        self._rolemap = rolemap
        self._market = market
        self._gateway = gateway
        self._threshold = confidence_threshold

    # -- cost ---------------------------------------------------------------

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        """Priced before anything is spent, for the first-run confirmation."""
        snapshot = await self._profile.snapshot(owner_id)
        if not snapshot.evidence:
            raise ValidationError(
                "connect a source or upload a resume before analysing", evidence=0
            )
        estimate = await self._gateway.estimate(
            owner_id,
            task="assessment.run",
            template=load_template("skill_assessment", "v1"),
            inputs=_assessment_inputs(
                snapshot, CitationHandles(e.id for e in snapshot.evidence), existing=()
            ),
            untrusted=frozenset({"evidence", "timeline"}),
        )
        return {
            "cost_usd": str(estimate.cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
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
            template=load_template("skill_assessment", "v1"),
            inputs=_assessment_inputs(snapshot, handles, existing=tuple(existing.items())),
            output_schema=_Assessment,
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

        # Follow-up questions are a separate round the job requests next
        # (ADR 0012), so the page can show them being generated.
        await self._store(
            owner_id,
            snapshot_version=snapshot.version,
            dimensions=dimensions,
            existing=existing,
            model_id=result.model_id,
            template_version=result.template_version,
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

    # -- follow-up questions ------------------------------------------------

    async def questions(
        self,
        owner_id: uuid.UUID,
        *,
        unanswered_only: bool = True,
        page: int = 1,
        page_size: int | None = None,
    ) -> Page[QuestionView]:
        """Oldest first, the order they were raised in.

        The store lists newest first, so the order is turned here and the page
        cut after it: one user's open questions, a handful per round.
        """
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.questions.get_list(
                FollowUpQuestionFilter(
                    is_answered=False if unanswered_only else None, is_retired=False
                )
            )
        views = [
            QuestionView(
                id=q.id,
                dimension_key=q.dimension_key,
                text=q.text,
                why=q.why,
                options=q.options,
                answer=q.answer,
            )
            for q in reversed(found)
        ]
        return paginate(views, page, page_size)

    async def answer(self, owner_id: uuid.UUID, question_id: uuid.UUID, answer: str) -> None:
        """An answer becomes self-reported Evidence and bumps the profile."""
        async with self._uow.for_owner(owner_id) as mine:
            question = await mine.questions.get(question_id)
            if question is None:
                raise NotFoundError("question not found", question_id=str(question_id))
            question.answered(answer, at=utcnow())
            await mine.questions.update(question)
            mine.record(
                QuestionAnswered(
                    owner_id=owner_id,
                    question_id=question.id,
                    dimension_key=question.dimension_key,
                )
            )

        await self._profile.record_answer(
            owner_id, question_id=str(question.id), question=question.text, answer=answer
        )

    async def request_questions(
        self, owner_id: uuid.UUID, *, trigger: QuestionRoundTrigger
    ) -> uuid.UUID | None:
        """Open a round for the latest assessment's thin dimensions (ADR 0012).

        Returns the round for the caller to queue, or ``None`` when there is
        nothing to ask: no assessment yet, or every dimension is confident
        enough. A round still generating is superseded, so the newest evidence
        wins and only one set of questions is written.
        """
        async with self._uow.for_owner(owner_id) as mine:
            newest = await mine.assessments.get_list(SkillAssessmentFilter(), page_size=1)
            if not newest:
                return None
            scores = await mine.scores.get_list(AssessedScoreFilter(assessment_id=newest[0].id))
            if not needs_follow_up(scores, threshold=self._threshold):
                return None

            now = utcnow()
            for running in await mine.rounds.get_list(
                QuestionRoundFilter(status=QuestionRoundStatus.GENERATING)
            ):
                running.superseded(now)
                await mine.rounds.update(running)
            requested = await mine.rounds.create(
                QuestionRound.requested(
                    owner_id=owner_id, assessment_id=newest[0].id, trigger=trigger, at=now
                )
            )
        log.info("assessment.questions_requested", round_id=str(requested.id), trigger=trigger)
        return requested.id

    async def generate_questions(self, owner_id: uuid.UUID, round_id: uuid.UUID) -> None:
        """The worker job. An expected failure is recorded on the round with
        its stable code and not retried: a retry would spend the key again."""
        async with self._uow.for_owner(owner_id) as mine:
            requested = await mine.rounds.get(round_id)
        if requested is None:
            raise NotFoundError("question round not found", round_id=str(round_id))
        if not requested.is_generating:
            return

        try:
            await self._generate_questions(owner_id, requested)
        except DomainError as exc:
            log.warning("assessment.questions_failed", round_id=str(round_id), code=str(exc.code))
            await self._fail_round(owner_id, round_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fail_round(
                owner_id,
                round_id,
                code="internal",
                message="Generating questions stopped unexpectedly. Try again in a moment.",
            )
            raise

    async def latest_round(self, owner_id: uuid.UUID) -> QuestionRoundView | None:
        async with self._uow.for_owner(owner_id) as mine:
            newest = await mine.rounds.get_list(QuestionRoundFilter(), page_size=1)
        if not newest:
            return None
        found = newest[0]
        return QuestionRoundView(
            id=found.id,
            trigger=str(found.trigger),
            status=str(found.status),
            question_count=found.question_count,
            created_at=found.created_at,
            finished_at=found.finished_at,
            error_code=found.error_code,
            error_message=found.error_message,
        )

    # -- fit ----------------------------------------------------------------

    async def compute_fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """One projection per User x Role, stored with its reasoning."""
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring roles")

        roles = await self._rolemap.roles(owner_id)
        if not roles:
            return []

        for role in roles:
            if not role.requirements:
                continue
            await self._project(
                owner_id,
                assessment,
                name=role.name,
                requirements=role.requirements,
                role_id=role.id,
            )

        async with self._uow.for_owner(owner_id) as mine:
            mine.record(RoleFitsComputed(owner_id=owner_id, roles=len(roles)))
        return await self.fits(owner_id)

    async def fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """The current fit per role — the bubble sizes.

        Every fit ever taken is kept as a snapshot; the newest per role or
        posting is the current one.
        """
        async with self._uow.for_owner(owner_id) as mine:
            snapshots = await mine.fits.get_list(RoleFitFilter())
        seen: set[uuid.UUID] = set()
        latest: list[FitView] = []
        for fit in snapshots:
            if fit.target in seen:
                continue
            seen.add(fit.target)
            latest.append(_fit_view(fit))
        return latest

    async def fit_for_private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> FitView:
        """Fit against a JD the user pasted, reading its requirements first.

        A pasted JD has no Role, so its requirements are read from its own text
        (on the user's key), then projected onto the user's dimensions like any
        role's. A fit already taken against the current analysis is reused, so
        planning and writing for the same JD pay for this once.
        """
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring a job description")
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id and fit.assessment_id == assessment.id:
                return fit

        posting = await self._market.private_posting(owner_id, posting_id)
        extraction = await self._gateway.run(
            owner_id,
            task="assessment.posting_requirements",
            template=load_template("posting_requirements", "v1"),
            inputs=_posting_inputs(posting),
            output_schema=_PostingRequirements,
            untrusted=frozenset({"posting"}),
        )
        requirements = tuple(
            RequirementView(r.statement, r.weight, r.expected_level)
            for r in extraction.value.requirements
        )
        await self._project(
            owner_id,
            assessment,
            name=f"{posting.title} at {posting.company_name}",
            requirements=requirements,
            private_posting_id=posting_id,
        )
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id:
                return fit
        raise NotFoundError("the fit disappeared immediately after being written")

    async def estimate_private_fit(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> Decimal:
        """What scoring a pasted JD would cost; nothing when it is already scored."""
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring a job description")
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id and fit.assessment_id == assessment.id:
                return Decimal(0)
        posting = await self._market.private_posting(owner_id, posting_id)
        extraction = await self._gateway.estimate(
            owner_id,
            task="assessment.posting_requirements",
            template=load_template("posting_requirements", "v1"),
            inputs=_posting_inputs(posting),
            untrusted=frozenset({"posting"}),
        )
        # The projection's requirements are not known yet; the posting's own
        # text stands in for them, which over- rather than under-estimates.
        projection = await self._gateway.estimate(
            owner_id,
            task="assessment.fit",
            template=load_template("fit_projection", "v1"),
            inputs={
                "dimensions": _dimensions_block(assessment),
                "role_name": posting.title,
                "requirements": posting.description,
            },
            untrusted=frozenset({"requirements"}),
        )
        return extraction.cost_usd + projection.cost_usd

    async def _project(
        self,
        owner_id: uuid.UUID,
        assessment: AssessmentView,
        *,
        name: str,
        requirements: tuple[RequirementView, ...],
        role_id: uuid.UUID | None = None,
        private_posting_id: uuid.UUID | None = None,
    ) -> None:
        """Map requirements onto this user's dimensions, and store the fit."""
        user_scores = {d.key: d.score for d in assessment.dimensions}
        known_keys = set(user_scores)
        projection = await self._gateway.run(
            owner_id,
            task="assessment.fit",
            template=load_template("fit_projection", "v1"),
            inputs={
                "dimensions": _dimensions_block(assessment),
                "role_name": name,
                "requirements": "\n".join(
                    f"- {r.statement} (weight {r.weight}, expects {r.expected_level})"
                    for r in requirements
                ),
            },
            output_schema=_Projection,
            untrusted=frozenset({"requirements"}),
        )

        targets = [
            TargetScore(dimension_id=t.dimension_id, target=t.target)
            for t in projection.value.target_scores
            # A target for a dimension this user does not have is the model
            # drifting, not a new axis.
            if t.dimension_id in known_keys
        ]
        uncovered = _uncovered_from(projection.value, requirements, known_keys)
        fit = evaluate(user_scores=user_scores, targets=targets, uncovered=uncovered)
        statements = {r.statement for r in requirements}
        requirement_map: dict[str, str | None] = {statement: None for statement in statements}
        for mapping in projection.value.mappings:
            if mapping.requirement_statement in statements:
                requirement_map[mapping.requirement_statement] = (
                    mapping.dimension_id if mapping.dimension_id in known_keys else None
                )

        await self._store_fit(
            owner_id,
            assessment_id=assessment.id,
            role_id=role_id,
            private_posting_id=private_posting_id,
            fit=fit,
            targets=targets,
            requirements=requirements,
            requirement_map=requirement_map,
            reasoning=projection.value.reasoning,
            model_id=projection.model_id,
            template_version=projection.template_version,
        )

    async def matched_postings(
        self, owner_id: uuid.UUID, *, limit: int | None = DEFAULT_MATCHES
    ) -> list[MatchedPostingView]:
        """The best openings inside the user's analysed roles.

        Ranked by the role's current fit; no AI runs here. Pasted JDs are left
        out — they are the user's own, shown as "My own JD", not as a match —
        and each row says whether the user already watches that role there.
        """
        fit_by_role = {f.role_id: f.score for f in await self.fits(owner_id) if f.role_id}
        subscriptions = await self._market.subscriptions(owner_id)

        by_posting: dict[str, tuple[RoleView, Any]] = {}
        candidates: list[MatchCandidate] = []
        for role, postings in await self._rolemap.role_postings(owner_id):
            for posting in postings:
                if posting.visibility is not Visibility.SHARED:
                    continue
                by_posting[str(posting.id)] = (role, posting)
                candidates.append(
                    MatchCandidate(
                        posting_id=str(posting.id),
                        role_id=str(role.id),
                        role_name=role.name,
                        company_name=posting.company_name,
                        title=posting.title,
                        fit=fit_by_role.get(role.id),
                    )
                )

        try:
            ranked = rank_matches(candidates, limit=limit)
        except ValueError as exc:
            raise ValidationError(str(exc), limit=limit) from exc

        matched: list[MatchedPostingView] = []
        for candidate in ranked:
            role, posting = by_posting[candidate.posting_id]
            watching = next(
                (
                    s.id
                    for s in subscriptions
                    if s.company_id == posting.company_id
                    and (s.role_id == role.id or s.role_title.casefold() == role.name.casefold())
                ),
                None,
            )
            matched.append(
                MatchedPostingView(
                    posting_id=posting.id,
                    role_id=role.id,
                    role_name=role.name,
                    title=posting.title,
                    company_name=posting.company_name,
                    location=posting.location,
                    url=posting.url,
                    salary=posting.salary,
                    fit=candidate.fit,
                    subscription_id=watching,
                    source_kind=posting.source_kind,
                )
            )
        return matched

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

    async def _generate_questions(self, owner_id: uuid.UUID, requested: QuestionRound) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            scores = await mine.scores.get_list(
                AssessedScoreFilter(assessment_id=requested.assessment_id)
            )
            names = {d.key: d.name for d in await mine.dimensions.get_list(SkillDimensionFilter())}
        thin = sorted(
            needs_follow_up(scores, threshold=self._threshold), key=lambda s: s.dimension_key
        )

        written: list[_Question] = []
        if thin:
            block = "\n".join(
                f"- {s.dimension_key} ({names.get(s.dimension_key, s.dimension_key)}): "
                f"scored {s.score}, confidence {s.confidence:.2f}. {s.read}"
                for s in thin
            )
            snapshot = await self._profile.snapshot(owner_id)
            result = await self._gateway.run(
                owner_id,
                task="assessment.questions",
                template=load_template("follow_up_questions", "v1"),
                inputs={
                    "low_confidence_dimensions": block,
                    "evidence": _evidence_block(
                        snapshot, CitationHandles(e.id for e in snapshot.evidence)
                    ),
                },
                output_schema=_Questions,
                untrusted=frozenset({"evidence"}),
            )
            known = {s.dimension_key for s in thin}
            written = [q for q in result.value.questions if q.dimension_id in known]

        async with self._uow.for_owner(owner_id) as mine:
            current = await mine.rounds.get(requested.id)
            if current is None or not current.is_generating:
                # A newer round took over while the model ran; it writes the
                # questions, so these are dropped rather than doubled.
                return
            now = utcnow()
            for stale in await mine.questions.get_list(
                FollowUpQuestionFilter(is_answered=False, is_retired=False)
            ):
                stale.retire(now)
                await mine.questions.update(stale)
            for question in written:
                await mine.questions.create(
                    FollowUpQuestion(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=current.assessment_id,
                        dimension_key=question.dimension_id,
                        text=question.text,
                        why=question.why,
                        options=tuple(question.options),
                    )
                )
            current.ready(count=len(written), at=now)
            await mine.rounds.update(current)
            if written:
                mine.record(
                    QuestionsRaised(
                        owner_id=owner_id,
                        assessment_id=current.assessment_id,
                        count=len(written),
                    )
                )

    async def _fail_round(
        self, owner_id: uuid.UUID, round_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            failed = await mine.rounds.get(round_id)
            if failed is not None:
                failed.failed(code=code, message=message, at=utcnow())
                await mine.rounds.update(failed)

    async def _store_fit(
        self,
        owner_id: uuid.UUID,
        *,
        assessment_id: uuid.UUID,
        role_id: uuid.UUID | None,
        private_posting_id: uuid.UUID | None,
        fit: FitResult,
        targets: list[TargetScore],
        requirements: tuple[RequirementView, ...],
        requirement_map: dict[str, str | None],
        reasoning: str,
        model_id: str,
        template_version: str,
    ) -> None:
        if (role_id is None) == (private_posting_id is None):
            raise ValidationError("a fit is for exactly one role or one posting")
        async with self._uow.for_owner(owner_id) as mine:
            await mine.fits.create(
                RoleFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    assessment_id=assessment_id,
                    role_id=role_id,
                    private_posting_id=private_posting_id,
                    requirements=tuple(
                        {
                            "statement": r.statement,
                            "weight": r.weight,
                            "expected_level": r.expected_level,
                        }
                        for r in requirements
                    ),
                    requirement_map=requirement_map,
                    score=fit.score,
                    reasoning=reasoning,
                    target_profile={t.dimension_id: t.target for t in targets},
                    gaps=tuple(
                        {
                            "dimension_key": gap.dimension_id,
                            "user_score": gap.user_score,
                            "target_score": gap.target_score,
                            "delta": gap.delta,
                        }
                        for gap in fit.gaps
                    ),
                    uncovered=tuple(
                        {"statement": u.statement, "weight": u.weight} for u in fit.uncovered
                    ),
                    model_id=model_id,
                    template_version=template_version,
                )
            )


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
    score needs more evidence, the same rule that opens follow-up questions.
    """
    scores = await mine.scores.get_list(AssessedScoreFilter(assessment_id=assessment.id))
    thin = {s.dimension_key for s in needs_follow_up(scores, threshold=threshold)}
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
    )


def _assessment_inputs(
    snapshot: Any, handles: CitationHandles, *, existing: tuple[tuple[str, str], ...]
) -> dict[str, str]:
    return {
        "timeline": _timeline_block(snapshot),
        "evidence": _evidence_block(snapshot, handles),
        "existing_dimensions": (
            "\n".join(f"- {key}: {name}" for key, name in existing) or "(none yet)"
        ),
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
    return "\n".join(
        f"[{handles.handle(e.id)}] ({e.source}) {e.reference}: {e.fact}" for e in snapshot.evidence
    )


def _uncovered_from(
    projection: _Projection, requirements: tuple[RequirementView, ...], known_keys: set[str]
) -> list[UncoveredRequirement]:
    """Requirements that map to no dimension of this user's.

    Never dropped: no evidence at all is a different thing from a low score.
    """
    weights = {r.statement: r.weight for r in requirements}
    uncovered: list[UncoveredRequirement] = []
    mapped = {m.requirement_statement for m in projection.mappings if m.dimension_id in known_keys}
    for statement, weight in weights.items():
        if statement not in mapped:
            uncovered.append(UncoveredRequirement(statement=statement, weight=weight))
    return uncovered


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


def _dimensions_block(assessment: AssessmentView) -> str:
    return "\n".join(
        f"- {d.key}: {d.name} — scored {d.score}/100 (confidence {d.confidence:.2f})"
        for d in assessment.dimensions
    )


def _posting_inputs(posting: PostingView) -> dict[str, str]:
    return {
        "posting": (
            f"Title: {posting.title}\nCompany: {posting.company_name}\n"
            f"Location: {posting.location or 'not given'}\n\n{posting.description}"
        )
    }


def _fit_view(fit: RoleFit) -> FitView:
    # Set by the database when the fit was stored.
    assert fit.created_at is not None, "a stored fit has a creation time"
    return FitView(
        role_id=fit.role_id,
        private_posting_id=fit.private_posting_id,
        score=fit.score,
        reasoning=fit.reasoning,
        gaps=fit.gaps,
        uncovered=fit.uncovered,
        model_id=fit.model_id,
        created_at=fit.created_at,
        assessment_id=fit.assessment_id,
        target_profile=dict(fit.target_profile),
        requirements=tuple(
            RequirementView(r["statement"], r["weight"], r["expected_level"])
            for r in fit.requirements
        ),
        requirement_map=dict(fit.requirement_map),
    )
