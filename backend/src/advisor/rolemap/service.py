"""The role map: the roles the user's strengths point to, found on the market,
per user, on the user's key.

The analysis recommends candidate roles (ADR 0024); a build searches the
postings in the user's target locations for each and keeps the top k the
market has, k a setting (ADR 0029). The split that matters is who pays for what. Embedding and
matching run locally on the platform — plain computation. The user's key is
spent only on naming a role, pulling its requirements out, estimating its
interview difficulty (domain decision 7), and scoring the fits.

A posting the user brings themselves is evaluated here too, so the fit rules
live in one place (ADR 0028), but it is never on the map (Phase 8).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from advisor.market import (
    MarketService,
    PostingView,
    SalaryRange,
    Visibility,
    band_from,
    in_market,
    names_every_word,
)
from advisor.rolemap.domain import (
    DEFAULT_MATCHES,
    MAX_ROLE_REQUIREMENTS,
    MAX_ROLE_TITLE,
    MAX_STRENGTHS,
    MIN_POSTINGS_FOR_A_ROLE,
    BarBasis,
    BuildRun,
    BuildRunFilter,
    BuildRunStatus,
    CandidatePlacement,
    CandidatePlacementFilter,
    CandidateStrength,
    CandidateStrengthFilter,
    ClosingLifts,
    HiringBar,
    LineageEntry,
    MatchCandidate,
    OwnerRoleMap,
    OwnPostingError,
    PlacementOutcome,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingFit,
    PostingFitBasis,
    PostingFitFilter,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    Reconciliation,
    Role,
    RoleCandidate,
    RoleCandidateFilter,
    RoleChange,
    RoleFilter,
    RoleFit,
    RoleFitFilter,
    RoleFitsComputed,
    RoleMapBuildFinished,
    RoleMapUnitOfWork,
    RoleMember,
    RoleMemberFilter,
    RoleRequirement,
    RoleRequirementFilter,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    SkillGap,
    TargetScore,
    UncoveredRequirement,
    assign_postings,
    blend,
    choose_by_estimate,
    closing_lifts,
    evaluate,
    fit_estimates,
    get_own_posting_key,
    get_posting_fit,
    get_requirements_digest,
    keep_on_market,
    max_role_count,
    parse_own_posting,
    rank_matches,
    reconcile,
    spearman,
)
from kernel.ai_gateway import AiGateway, PromptTemplate
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.embeddings import embed
from kernel.errors import DomainError, NotFoundError, ValidationError
from kernel.logging import get_logger

__all__ = [
    "BuildRequestView",
    "BuildRunView",
    "CandidateInput",
    "FitView",
    "MarketWait",
    "MatchedPostingView",
    "OwnPostingView",
    "PostingFitView",
    "RequirementView",
    "RoleCandidateView",
    "RoleMapService",
    "RoleView",
    "StrengthInput",
]

log = get_logger(__name__)

# The user's key is spent per role, so a first run has a predictable cost.
MAX_POSTINGS_IN_A_PROMPT = 12
MAX_DESCRIPTION_CHARS = 4000


class _Requirement(BaseModel):
    statement: str
    weight: float = Field(ge=0.0, le=1.0)
    expected_level: str


class _RoleExtraction(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_coherent: bool = True
    requirements: list[_Requirement] = Field(min_length=1, max_length=MAX_ROLE_REQUIREMENTS)


class _DifficultyEstimate(BaseModel):
    difficulty: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class _Mapping(BaseModel):
    requirement_statement: str
    dimension_id: str | None = None


class _Target(BaseModel):
    dimension_id: str
    target: int = Field(ge=0, le=100)


class _Projection(BaseModel):
    mappings: list[_Mapping]
    target_scores: list[_Target]
    reasoning: str


@dataclass(frozen=True, slots=True)
class _Group:
    """One candidate's openings, before they are analysed into a role."""

    candidate: RoleCandidate
    keys: set[str]
    postings: list[PostingView]


@dataclass(frozen=True, slots=True)
class CandidateInput:
    """One role the analysis recommended, as ``assessment`` hands it over:
    best fit first, resting on the user's dimension keys (ADR 0024)."""

    title: str
    description: str
    dimension_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrengthInput:
    """One of the user's dimensions as the analysis that recommended the
    candidates scored it, handed over with them. The local fit estimate weighs
    it (ADR 0027), and the fits are scored against it (ADR 0028)."""

    dimension_key: str
    name: str
    read: str
    score: int
    confidence: float

    @property
    def weight(self) -> float:
        """Score times confidence, from 0 to 1: how much the estimate leans on it."""
        return self.score / 100 * self.confidence


@dataclass(frozen=True, slots=True)
class RoleCandidateView:
    """A recommended candidate, and what the latest build that read it made of
    it (its ``CandidatePlacement``): the role it became, or none when it fell
    outside the top k or the user's target locations lack openings for it.
    Before any build has read it, no role and no openings."""

    id: uuid.UUID
    rank: int
    title: str
    description: str
    dimension_keys: tuple[str, ...]
    role_id: uuid.UUID | None
    opening_count: int
    # The local estimate that chose the k (ADR 0027); never a fit.
    fit_estimate: float | None = None
    # `placed`, `outside_top_k` or `too_few_openings`; none before a build.
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class RequirementView:
    statement: str
    weight: float
    expected_level: str


@dataclass(frozen=True, slots=True)
class RoleView:
    """One bubble. X is the hiring bar, Y is salary; size is its fit
    (``FitView``), kept apart from the role because it belongs to the
    User x Role pair."""

    id: uuid.UUID
    name: str
    hiring_bar: int
    bar_basis: str
    bar_confidence: float
    bar_reasoning: str | None
    opening_count: int
    salary_bands: dict[str, Any]
    requirements: tuple[RequirementView, ...]
    is_coherent: bool


@dataclass(frozen=True, slots=True)
class FitView:
    """The user's fit to one of their roles: a bubble's size (ADR 0028)."""

    role_id: uuid.UUID
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
class PostingFitView:
    """The user's fit to one posting, worked out locally from an AI fit
    (Phase 8): what the Advisor plans against when aimed at it."""

    posting_key: str
    basis: str
    score: int
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    requirements: tuple[RequirementView, ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    assessment_id: uuid.UUID
    created_at: datetime

    def lifts(self) -> ClosingLifts:
        """Fit points each gap is worth, by the fit's own arithmetic."""
        return closing_lifts(
            gaps=[
                SkillGap(g["dimension_key"], g["user_score"], g["target_score"]) for g in self.gaps
            ],
            uncovered=[UncoveredRequirement(u["statement"], u["weight"]) for u in self.uncovered],
        )


@dataclass(frozen=True, slots=True)
class OwnPostingView:
    """A posting the user brought themselves, to aim the Advisor at (Phase 8):
    the JD they pasted, where reading and scoring it stands, and its fit."""

    private_job_posting_id: uuid.UUID
    title: str
    company_name: str
    # The latest run: `running`, `ready` or `failed`; none before any.
    status: str | None
    error_code: str | None
    error_message: str | None
    fit: int | None
    # Scored against an analysis older than the latest: worth rescoring.
    is_stale: bool
    scored_at: datetime | None


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
    # The crawl source kind (atsBoard, jsonLd, publicApi); never a site that
    # forbids crawling (domain decision 6).
    source_kind: str | None = None
    # The job site to credit beside the opening's link, when it was found
    # through that site's API (ADR 0025).
    credited_to: str | None = None


@dataclass(frozen=True, slots=True)
class BuildRunView:
    """Whether a role-map build is waiting or running, and why the last one
    could not finish."""

    id: uuid.UUID
    status: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    # Waiting for market sources to be fetched, rather than for an analysis.
    is_waiting_for_market: bool = False
    awaited_since: datetime | None = None
    # The target locations it was built for, the sources it read, and how old
    # the oldest of them was.
    locations: tuple[str, ...] = ()
    needed_source_ids: tuple[uuid.UUID, ...] = ()
    market_data_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.status in (BuildRunStatus.WAITING, BuildRunStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class BuildRequestView:
    """What asking for a build did. ``should_queue`` is true only when this
    request started a build, so the caller queues it exactly once;
    ``should_await_market`` only when it began waiting for market sources, so
    the caller schedules exactly one check on them (ADR 0027)."""

    build: BuildRunView
    should_queue: bool
    should_await_market: bool = False


class MarketWait(StrEnum):
    """What a check on a build waiting for the market found."""

    # Its sources are fetched, or its deadline passed: it started; queue it.
    START = "start"
    # Still waiting: check again later.
    WAIT = "wait"
    # Nothing to do: it is not waiting for the market any more.
    DONE = "done"


class RoleMapService:
    def __init__(
        self,
        uow: RoleMapUnitOfWork,
        *,
        market: MarketService,
        gateway: AiGateway,
        embedding_model: str,
        top_k: int,
        candidate_count: int,
    ) -> None:
        if not 1 <= top_k <= candidate_count:
            raise ValueError("a build keeps between 1 and candidate_count roles")
        self._uow = uow
        self._market = market
        self._gateway = gateway
        self._embedding_model = embedding_model
        # How many recommended roles a build keeps, names, analyses and
        # scores, and how many candidates an analysis may hand over (ADR 0029).
        self._top_k = top_k
        self._candidate_count = candidate_count

    async def roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        """The live roles, newest first, each with its requirements, weightiest
        first. One user's map: k roles and their own, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            roles = await mine.roles.get_list(RoleFilter(is_retired=False))
            requirements = (
                await mine.requirements.get_list(
                    RoleRequirementFilter(role_ids=tuple(r.id for r in roles))
                )
                if roles
                else []
            )
        by_role: dict[uuid.UUID, list[RoleRequirement]] = {}
        for requirement in requirements:
            by_role.setdefault(requirement.role_id, []).append(requirement)
        return [_role_view(role, by_role.get(role.id, [])) for role in roles]

    async def role_postings(self, owner_id: uuid.UUID) -> list[tuple[RoleView, list[PostingView]]]:
        """Each analysed role with the open postings grouped into it.

        Postings that have since expired, or left the user's scope, drop out:
        membership is resolved against the current scope, not stored copies.
        """
        roles = await self.roles(owner_id)
        if not roles:
            return []
        async with self._uow.for_owner(owner_id) as mine:
            members = await mine.members.get_list(
                RoleMemberFilter(role_ids=tuple(role.id for role in roles))
            )
        keys_by_role: dict[uuid.UUID, list[str]] = {}
        for member in members:
            keys_by_role.setdefault(member.role_id, []).append(member.posting_key)

        in_scope = {_posting_key(p): p for p in await self._market.postings_in_scope(owner_id)}
        return [
            (role, [in_scope[key] for key in keys_by_role.get(role.id, []) if key in in_scope])
            for role in roles
        ]

    async def map_roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        """The live roles as the role map draws them: each with the openings it
        has now, not the count stored when it was built.

        A posting that has expired, dropped off its search's list, or left the
        user's locations since the build is not counted, so a bubble says what
        "Top matched openings" can list for its role.
        """
        return [
            replace(role, opening_count=len(postings))
            for role, postings in await self.role_postings(owner_id)
        ]

    # -- candidates (ADR 0024) -----------------------------------------------

    async def replace_candidates(
        self,
        owner_id: uuid.UUID,
        assessment_id: uuid.UUID,
        candidates: Sequence[CandidateInput],
        strengths: Sequence[StrengthInput] = (),
    ) -> list[RoleCandidateView]:
        """The roles an analysis recommended, replacing the last analysis's.

        Called by ``assessment`` once its scores are stored; the next build
        asks the market to search for their titles (ADR 0027) and looks for
        them among what it finds. At most ``ROLE_CANDIDATE_COUNT``, in
        the analysis's order.
        """
        if len(candidates) > self._candidate_count:
            raise ValidationError(
                f"an analysis recommends at most {self._candidate_count} roles",
                candidates=len(candidates),
            )
        _check_strengths(strengths)
        async with self._uow.for_owner(owner_id) as mine:
            for previous in await mine.candidates.get_list(RoleCandidateFilter()):
                await mine.candidates.delete(previous.id)
            for old in await mine.strengths.get_list(CandidateStrengthFilter()):
                await mine.strengths.delete(old.id)
            for strength in {s.dimension_key: s for s in strengths}.values():
                await mine.strengths.create(
                    CandidateStrength(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=assessment_id,
                        dimension_key=strength.dimension_key,
                        name=strength.name,
                        read=strength.read,
                        weight=strength.weight,
                        score=strength.score,
                        confidence=strength.confidence,
                    )
                )
            stored = [
                await mine.candidates.create(
                    RoleCandidate(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        assessment_id=assessment_id,
                        rank=rank,
                        title=candidate.title,
                        description=candidate.description,
                        dimension_keys=candidate.dimension_keys,
                    )
                )
                for rank, candidate in enumerate(candidates)
            ]
        log.info("rolemap.candidates_replaced", candidates=len(stored))
        return [_candidate_view(c, None) for c in stored]

    async def candidates(self, owner_id: uuid.UUID) -> list[RoleCandidateView]:
        """The latest analysis's candidates, in its order, each with what the
        latest build that read it made of it, if any build has."""
        candidates = await self._candidates(owner_id)
        placements = await self._latest_placements(owner_id, candidates)
        return [_candidate_view(c, placements.get(c.id)) for c in candidates]

    async def _latest_placements(
        self, owner_id: uuid.UUID, candidates: list[RoleCandidate]
    ) -> dict[uuid.UUID, CandidatePlacement]:
        """Each candidate's placement by the newest build that read it. A
        build that found nothing in scope places nobody, so the build before
        it still speaks for them."""
        if not candidates:
            return {}
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.placements.get_list(
                CandidatePlacementFilter(candidate_ids=tuple(c.id for c in candidates))
            )
        latest: dict[uuid.UUID, CandidatePlacement] = {}
        for placement in found:
            if placement.candidate_id is not None:
                latest.setdefault(placement.candidate_id, placement)
        return latest

    async def _candidates(self, owner_id: uuid.UUID) -> list[RoleCandidate]:
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.candidates.get_list(RoleCandidateFilter())
        return sorted(found, key=lambda c: c.rank)

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        """The most a role map can cost, before any money is spent.

        A ceiling, not a prediction: the api runs no embeddings, so it prices
        the most roles these postings could make, with each posting an opening
        for one role at most, capped at the k recommended roles a build keeps,
        each sent with the costliest prompt they could fill. Where a search
        will run before the build (ADR 0027), what is stored now says nothing
        about what it will find, so the ceiling is the full k.
        """
        postings = await self._market.postings_in_scope(owner_id)
        max_roles = max_role_count(len(postings), ceiling=self._top_k)
        if await self._market.has_searchable_place(owner_id):
            max_roles = self._top_k
        if max_roles == 0:
            return {"max_roles": 0, "cost_usd": "0", "model_id": None}

        template = load_template("role_extraction", "v1")
        sample = _postings_block(sorted(postings, key=_prompt_length, reverse=True))
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.extract",
            template=template,
            inputs={"postings": sample},
            untrusted=frozenset({"postings"}),
        )
        # Two calls per role: extraction, then the difficulty estimate.
        total = estimate.cost_usd * max_roles * 2
        return {
            "max_roles": max_roles,
            "cost_usd": str(total.quantize(estimate.cost_usd)),
            "model_id": estimate.model_id,
            "rate_is_published": estimate.rate_is_published,
        }

    # -- builds (ADR 0006, ADR 0018) -----------------------------------------

    async def request_build(self, owner_id: uuid.UUID, *, wait: bool) -> BuildRequestView:
        """Record a build, waiting for an analysis or for the market.

        One build is open at a time: asking again while one is open returns
        it. A build that need not wait for an analysis asks the market for
        what it reads first (ADR 0027): it starts at once when everything is
        fresh, and otherwise waits for the sources being fetched. Whether to
        wait for an analysis is ``advisor.activity``'s rule, not this
        component's.
        """
        async with self._uow.for_owner(owner_id) as mine:
            open_builds = await mine.builds.get_list(
                BuildRunFilter(statuses=(BuildRunStatus.WAITING, BuildRunStatus.RUNNING)),
                page_size=1,
            )
            if open_builds:
                current = open_builds[0]
                asks_market = current.is_waiting and not current.awaited_since and not wait
                if not asks_market:
                    return BuildRequestView(_build_view(current), should_queue=False)
                build_id = current.id
            else:
                created = await mine.builds.create(
                    BuildRun.requested(owner_id=owner_id, at=utcnow(), wait=True)
                )
                build_id = created.id
                log.info("rolemap.build_requested", build_id=str(created.id), waiting=wait)
                if wait:
                    return BuildRequestView(_build_view(created), should_queue=False)
        return await self._ask_market(owner_id, build_id)

    async def release_waiting(self, owner_id: uuid.UUID) -> BuildRequestView | None:
        """The analysis a build waited for ended without a result: the build
        goes on, asking the market for what it reads first."""
        async with self._uow.for_owner(owner_id) as mine:
            waiting = await mine.builds.get_list(
                BuildRunFilter(statuses=(BuildRunStatus.WAITING,)), page_size=1
            )
        if not waiting or waiting[0].awaited_since is not None:
            return None
        return await self._ask_market(owner_id, waiting[0].id)

    async def _ask_market(self, owner_id: uuid.UUID, build_id: uuid.UUID) -> BuildRequestView:
        """Ask the market for every source this build reads: the candidates'
        searches in the user's places, and the baseline boards. Only titles and
        places cross."""
        titles = [candidate.title for candidate in await self._candidates(owner_id)]
        places = await self._market.target_locations(owner_id)
        request = await self._market.request_sources(titles=titles, places=places)
        now = utcnow()
        async with self._uow.for_owner(owner_id) as mine:
            build = await mine.builds.get(build_id)
            if build is None or not build.is_waiting:
                raise NotFoundError("waiting role map build not found", build_id=str(build_id))
            build.wait_for_market(
                needed=request.needed, due=request.due, locations=tuple(places), at=now
            )
            if not request.due:
                build.start(now)
            stored = await mine.builds.update(build)
        log.info(
            "rolemap.build_asked_market",
            build_id=str(build_id),
            needed=len(request.needed),
            due=len(request.due),
        )
        return BuildRequestView(
            _build_view(stored),
            should_queue=not request.due,
            should_await_market=bool(request.due),
        )

    async def check_market(
        self, owner_id: uuid.UUID, build_id: uuid.UUID, *, deadline: timedelta
    ) -> MarketWait:
        """Start a build waiting for the market once every source it waits for
        has been fetched, or once ``deadline`` has passed since it asked; then
        it builds on what is stored (ADR 0027)."""
        async with self._uow.for_owner(owner_id) as mine:
            build = await mine.builds.get(build_id)
        if build is None or not build.is_waiting_for_market or build.awaited_since is None:
            return MarketWait.DONE
        pending = await self._market.pending_sources(build.awaited_source_ids)
        now = utcnow()
        if pending and now - build.awaited_since < deadline:
            return MarketWait.WAIT
        async with self._uow.for_owner(owner_id) as mine:
            current = await mine.builds.get(build_id)
            if current is None or not current.is_waiting_for_market:
                return MarketWait.DONE
            current.start(now)
            await mine.builds.update(current)
        log.info(
            "rolemap.build_released_by_market",
            build_id=str(build_id),
            still_due=len(pending),
            at_deadline=bool(pending),
        )
        return MarketWait.START

    async def last_finished_build(self, owner_id: uuid.UUID) -> BuildRunView | None:
        """The newest build that finished with a map: what the map on screen
        was built for, and how old its market was."""
        async with self._uow.for_owner(owner_id) as mine:
            ready = await mine.builds.get_list(
                BuildRunFilter(statuses=(BuildRunStatus.READY,)), page_size=1
            )
        return _build_view(ready[0]) if ready else None

    async def latest_build(self, owner_id: uuid.UUID) -> BuildRunView | None:
        async with self._uow.for_owner(owner_id) as mine:
            newest = await mine.builds.get_list(BuildRunFilter(), page_size=1)
        return _build_view(newest[0]) if newest else None

    async def build(self, owner_id: uuid.UUID, build_id: uuid.UUID) -> list[RoleView]:
        """The worker job for one recorded build.

        An expected failure is recorded on the build with its stable code and
        not raised: a retry would spend the key again. Anything else is recorded
        as ``internal`` and re-raised for the log.
        """
        async with self._uow.for_owner(owner_id) as mine:
            requested = await mine.builds.get(build_id)
        if requested is None:
            raise NotFoundError("role map build not found", build_id=str(build_id))
        if not requested.is_running:
            return []

        try:
            roles = await self.recluster(owner_id, build_id)
        except DomainError as exc:
            log.warning("rolemap.build_failed", build_id=str(build_id), code=str(exc.code))
            await self.fail_build(owner_id, build_id, code=str(exc.code), message=exc.message)
            return []
        except Exception:
            await self.fail_build(
                owner_id,
                build_id,
                code="internal",
                message="Building the role map stopped unexpectedly. Try again in a moment.",
            )
            raise

        market_data_at = await self._market.oldest_fetch(requested.needed_source_ids)
        async with self._uow.for_owner(owner_id) as mine:
            done = await mine.builds.get(build_id)
            if done is not None and done.is_running:
                done.ready(utcnow(), market_data_at=market_data_at)
                await mine.builds.update(done)
                # Its fits are scored once, now, whatever it changed (ADR 0024).
                mine.record(
                    RoleMapBuildFinished(
                        owner_id=owner_id, build_id=build_id, status=str(BuildRunStatus.READY)
                    )
                )
        return roles

    async def fail_build(
        self, owner_id: uuid.UUID, build_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        """Close a build without a result. Also how ``advisor.activity`` gives
        up on a build whose worker never came back. The fits are still scored:
        an analysis that asked for this build has new scores to show against
        the roles that are there."""
        async with self._uow.for_owner(owner_id) as mine:
            failed = await mine.builds.get(build_id)
            if failed is None or not failed.is_open:
                return
            failed.failed(code=code, message=message, at=utcnow())
            await mine.builds.update(failed)
            mine.record(
                RoleMapBuildFinished(
                    owner_id=owner_id, build_id=build_id, status=str(BuildRunStatus.FAILED)
                )
            )

    async def recluster(self, owner_id: uuid.UUID, build_id: uuid.UUID) -> list[RoleView]:
        """Rebuild this user's role map from the latest analysis's candidates,
        as the work of build ``build_id``, which records what it made of each.

        Role ids survive: a goal or a saved fit pointing at a role must still
        find it after a crawl changes the underlying postings. With no
        candidates yet — no analysis has succeeded — nothing is built, so
        nothing is spent on a map the user never priced.
        """
        candidates = await self._candidates(owner_id)
        if candidates:
            await self._build_recommended(owner_id, candidates, build_id=build_id)
        else:
            log.info("rolemap.no_candidates", owner_id=str(owner_id))
        return await self.roles(owner_id)

    async def _build_recommended(
        self, owner_id: uuid.UUID, candidates: list[RoleCandidate], *, build_id: uuid.UUID
    ) -> None:
        """The top k of the candidates the market has, analysed on the user's
        key; nothing is spent on the rest (ADR 0029).

        Each candidate's openings start with what its own search found; the
        k kept are those that read most like the user's strengths, by a
        local estimate that spends nothing (ADR 0027). Candidates the market
        lacks are left unplaced, and roles that no longer come from a kept
        candidate are retired by reconciliation.
        """
        scope = await self._scope_vectors(owner_id)
        if not scope:
            # An empty market says nothing about the roles, or about where each
            # candidate stands: keep both as they are.
            log.info("rolemap.nothing_in_scope", owner_id=str(owner_id))
            return

        vectors = embed(
            ["\n".join((c.title, c.title, c.description)) for c in candidates],
            model_name=self._embedding_model,
        )
        postings = [posting for _key, posting, _vector in scope]
        searched_by = await self._searched_by(owner_id, candidates, postings)
        assigned = assign_postings(
            vectors,
            [vector for _key, _posting, vector in scope],
            [
                frozenset(
                    index
                    for index, candidate in enumerate(candidates)
                    if names_every_word(posting.title, candidate.title)
                )
                for posting in postings
            ],
            searched_by=searched_by,
        )
        members: list[list[int]] = [[] for _ in candidates]
        for posting_index, candidate_index in enumerate(assigned):
            if candidate_index is not None:
                members[candidate_index].append(posting_index)
        counts = {c.id: len(members[i]) for i, c in enumerate(candidates)}
        eligible = keep_on_market([len(m) for m in members], limit=len(candidates))
        estimates = await self._estimates(owner_id, candidates, members, eligible, scope)
        keep = choose_by_estimate(estimates, eligible, limit=self._top_k)
        groups = [
            _Group(
                candidate=candidates[index],
                keys={scope[j][0] for j in members[index]},
                postings=[postings[j] for j in members[index]],
            )
            for index in keep
        ]
        log.info(
            "rolemap.selected",
            owner_id=str(owner_id),
            candidates=len(candidates),
            candidates_on_market=len(eligible),
            candidates_kept=len(groups),
            postings_in_scope=len(scope),
            postings_searched=sum(1 for found in searched_by if found),
        )

        previous = await self._previous_members(owner_id)
        reconciliation = reconcile(
            previous=previous,
            clusters=[group.keys for group in groups],
            new_id=lambda: str(uuid.uuid4()),
        )

        placed: dict[uuid.UUID, uuid.UUID] = {}
        for index, group in enumerate(groups):
            role_id = uuid.UUID(reconciliation.assignments[index])
            placed[group.candidate.id] = role_id
            # The same postings as the last analysis: nothing for the key to
            # redo, so a rebuild on an unchanged market is free.
            if previous.get(str(role_id)) == group.keys and await self._keep_role(
                owner_id, role_id=role_id, postings=group.postings
            ):
                continue
            await self._analyse(
                owner_id,
                role_id=role_id,
                keys=group.keys,
                postings=group.postings,
                block=_postings_block(group.postings),
            )

        await self._record_lineage(owner_id, reconciliation)
        await self._place_candidates(
            owner_id,
            build_id,
            candidates,
            placed=placed,
            counts=counts,
            eligible={candidates[i].id for i in eligible},
            estimates={candidates[i].id: estimates[i] for i in eligible},
        )

    async def _searched_by(
        self, owner_id: uuid.UUID, candidates: list[RoleCandidate], postings: list[PostingView]
    ) -> list[frozenset[int]]:
        """For each posting in scope, the candidates whose own search found
        it: the market searched each candidate's title in the user's places."""
        found = await self._market.search_results(
            titles=[c.title for c in candidates],
            places=await self._market.target_locations(owner_id),
        )
        by_posting: dict[uuid.UUID, set[int]] = {}
        for index, candidate in enumerate(candidates):
            for posting_id in found.get(candidate.title, []):
                by_posting.setdefault(posting_id, set()).add(index)
        return [frozenset(by_posting.get(posting.id, ())) for posting in postings]

    async def _estimates(
        self,
        owner_id: uuid.UUID,
        candidates: list[RoleCandidate],
        members: list[list[int]],
        eligible: list[int],
        scope: list[tuple[str, PostingView, list[float]]],
    ) -> list[float]:
        """The local fit estimate of each eligible candidate; 0 for the rest.
        Only the user's dimension names and reads are embedded, here."""
        async with self._uow.for_owner(owner_id) as mine:
            strengths = await mine.strengths.get_list(CandidateStrengthFilter())
        estimates = [0.0] * len(candidates)
        if not eligible or not strengths:
            return estimates
        strengths = sorted(strengths, key=lambda s: s.dimension_key)
        dimension_vectors = embed(
            [f"{s.name}. {s.read}" for s in strengths], model_name=self._embedding_model
        )
        position = {s.dimension_key: d for d, s in enumerate(strengths)}
        found = fit_estimates(
            dimension_vectors,
            [s.weight for s in strengths],
            [[scope[j][2] for j in members[index]] for index in eligible],
            [
                frozenset(
                    position[key] for key in candidates[index].dimension_keys if key in position
                )
                for index in eligible
            ],
        )
        for index, estimate in zip(eligible, found, strict=True):
            estimates[index] = estimate
        return estimates

    async def _place_candidates(
        self,
        owner_id: uuid.UUID,
        build_id: uuid.UUID,
        candidates: list[RoleCandidate],
        *,
        placed: dict[uuid.UUID, uuid.UUID],
        counts: dict[uuid.UUID, int],
        eligible: set[uuid.UUID],
        estimates: dict[uuid.UUID, float],
    ) -> None:
        """Record what the build made of each candidate, as the build's own
        record: its role, or why none. The candidate itself is not touched.

        An analysis that finished during the build has replaced the set; its
        candidates wait for the build that follows it, so the ones this build
        read and no longer exist are skipped.
        """
        async with self._uow.for_owner(owner_id) as mine:
            for read in candidates:
                if await mine.candidates.get(read.id) is None:
                    continue
                role_id = placed.get(read.id)
                await mine.placements.create(
                    CandidatePlacement(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        build_run_id=build_id,
                        candidate_id=read.id,
                        rank=read.rank,
                        title=read.title,
                        outcome=(
                            PlacementOutcome.PLACED
                            if role_id is not None
                            else PlacementOutcome.OUTSIDE_TOP_K
                            if read.id in eligible
                            else PlacementOutcome.TOO_FEW_OPENINGS
                        ),
                        opening_count=counts.get(read.id, 0),
                        role_id=role_id,
                        fit_estimate=estimates.get(read.id),
                    )
                )

    async def _analyse(
        self,
        owner_id: uuid.UUID,
        *,
        role_id: uuid.UUID,
        keys: set[str],
        postings: list[PostingView],
        block: str,
    ) -> None:
        """Name a role, read out what it requires and estimate its bar, on the
        user's key: two calls. ``block`` is the untrusted text read: a
        candidate's openings."""
        extracted = await self._gateway.run(
            owner_id,
            task="rolemap.extract",
            template=load_template("role_extraction", "v1"),
            inputs={"postings": block},
            output_schema=_RoleExtraction,
            untrusted=frozenset({"postings"}),
        )
        requirements_block = "\n".join(
            f"- {r.statement} (weight {r.weight}, {r.expected_level})"
            for r in extracted.value.requirements
        )
        difficulty = await self._gateway.run(
            owner_id,
            task="rolemap.difficulty",
            template=load_template("difficulty_estimate", "v1"),
            inputs={
                "role_name": extracted.value.name,
                "requirements": requirements_block,
                "postings": block,
            },
            output_schema=_DifficultyEstimate,
            untrusted=frozenset({"postings"}),
        )
        # Phase 1 has no InterviewReports, so every bar is an estimate.
        bar = blend(
            estimated=difficulty.value.difficulty,
            estimate_confidence=difficulty.value.confidence,
            reported=None,
            reporter_count=0,
        )
        await self._store_role(
            owner_id,
            role_id=role_id,
            keys=keys,
            postings=postings,
            extraction=extracted.value,
            bar=bar,
            bar_reasoning=difficulty.value.reasoning,
            model_id=extracted.model_id,
            template_version=extracted.template_version,
        )

    # -- fits (ADR 0028) -----------------------------------------------------

    async def estimate_fits(
        self, owner_id: uuid.UUID, *, recommended: int | None = None
    ) -> dict[str, Any]:
        """The most scoring a build's fits can cost: one projection per role the
        map will hold — ``recommended`` roles, by default the ones on the map
        now — each with the most dimensions and requirements there can be. A
        ceiling, since nothing is known about the roles yet."""
        if recommended is None:
            recommended = len(await self.roles(owner_id))
        roles = min(recommended, self._top_k)
        if roles == 0:
            return {"cost_usd": "0", "roles": 0, "rate_is_published": True}
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.fit",
            template=_fit_template(),
            inputs=_worst_case_fit_inputs(),
            untrusted=frozenset({"requirements"}),
        )
        return {
            "cost_usd": str(estimate.cost_usd * roles),
            "roles": roles,
            "rate_is_published": estimate.rate_is_published,
        }

    async def compute_fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """One projection per role with requirements, against the scores the
        latest analysis handed over, stored with its reasoning. Run once per
        build, when it closes (ADR 0024)."""
        strengths = await self._strengths(owner_id)
        if not strengths:
            raise ValidationError("run an analysis before scoring roles")

        roles = await self.roles(owner_id)
        if not roles:
            return []

        assessment_id = strengths[0].assessment_id
        latest = await self._latest_role_fits(owner_id)
        reused = 0
        for role in roles:
            if not role.requirements:
                continue
            digest = _digest(role.requirements)
            current = latest.get(role.id)
            # The same requirements against the same scores come out the
            # same: a rebuild that changed neither spends nothing here.
            if current is not None and current.is_current(
                assessment_id=assessment_id, requirements_digest=digest
            ):
                reused += 1
                continue
            await self._project(owner_id, strengths, role, digest=digest)
        log.info("rolemap.fits_reused", roles=len(roles), reused=reused)

        async with self._uow.for_owner(owner_id) as mine:
            mine.record(RoleFitsComputed(owner_id=owner_id, roles=len(roles)))
        fits = await self.fits(owner_id)
        await self._log_estimate_agreement(owner_id, fits)
        return fits

    async def _latest_role_fits(self, owner_id: uuid.UUID) -> dict[uuid.UUID, RoleFit]:
        async with self._uow.for_owner(owner_id) as mine:
            snapshots = await mine.fits.get_list(RoleFitFilter())
        latest: dict[uuid.UUID, RoleFit] = {}
        for fit in snapshots:
            latest.setdefault(fit.role_id, fit)
        return latest

    async def fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """The current fit per role: the bubble sizes.

        Every fit ever taken is kept as a snapshot; the newest per role is the
        current one.
        """
        async with self._uow.for_owner(owner_id) as mine:
            snapshots = await mine.fits.get_list(RoleFitFilter())
        seen: set[uuid.UUID] = set()
        latest: list[FitView] = []
        for fit in snapshots:
            if fit.role_id in seen:
                continue
            seen.add(fit.role_id)
            latest.append(_fit_view(fit))
        return latest

    async def matched_postings(
        self,
        owner_id: uuid.UUID,
        *,
        limit: int | None = DEFAULT_MATCHES,
        role_id: uuid.UUID | None = None,
    ) -> list[MatchedPostingView]:
        """The best openings inside the user's roles, or inside one of them:
        the openings a Target in that role can name (ADR 0022).

        Ranked by the role's current fit; no AI runs here. Only shared
        postings are listed.

        Across all roles the list keeps each company's best opening only, so
        "Top matched" names different companies; one role's list
        (``role_id``) keeps all its openings, as its bubble counts them.
        """
        fit_by_role = {f.role_id: f.score for f in await self.fits(owner_id)}

        by_row: dict[tuple[str, str], tuple[RoleView, PostingView]] = {}
        candidates: list[MatchCandidate] = []
        for role, postings in await self.role_postings(owner_id):
            if role_id is not None and role.id != role_id:
                continue
            for posting in postings:
                if posting.visibility is not Visibility.SHARED:
                    continue
                by_row[(str(role.id), str(posting.id))] = (role, posting)
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
            ranked = rank_matches(candidates, limit=limit, one_per_company=role_id is None)
        except ValueError as exc:
            raise ValidationError(str(exc), limit=limit) from exc

        matched: list[MatchedPostingView] = []
        for candidate in ranked:
            role, posting = by_row[(candidate.role_id, candidate.posting_id)]
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
                    source_kind=posting.source_kind,
                    credited_to=posting.credited_to,
                )
            )
        return matched

    async def _strengths(self, owner_id: uuid.UUID) -> list[CandidateStrength]:
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.strengths.get_list(CandidateStrengthFilter())
        return sorted(found, key=lambda s: s.dimension_key)

    async def _project(
        self,
        owner_id: uuid.UUID,
        strengths: list[CandidateStrength],
        role: RoleView,
        *,
        digest: str,
    ) -> None:
        """Map a role's requirements onto the user's dimensions, and store the
        fit."""
        user_scores = {s.dimension_key: s.score for s in strengths}
        known_keys = set(user_scores)
        requirements = role.requirements
        projection = await self._gateway.run(
            owner_id,
            task="rolemap.fit",
            template=_fit_template(),
            inputs={
                "dimensions": _strengths_block(strengths),
                "role_name": role.name,
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
        requirement_map: dict[str, str | None] = {r.statement: None for r in requirements}
        for mapping in projection.value.mappings:
            if mapping.requirement_statement in requirement_map:
                requirement_map[mapping.requirement_statement] = (
                    mapping.dimension_id if mapping.dimension_id in known_keys else None
                )

        async with self._uow.for_owner(owner_id) as mine:
            await mine.fits.create(
                RoleFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    assessment_id=strengths[0].assessment_id,
                    role_id=role.id,
                    requirements=tuple(
                        {
                            "statement": r.statement,
                            "weight": r.weight,
                            "expected_level": r.expected_level,
                        }
                        for r in requirements
                    ),
                    requirement_map=requirement_map,
                    requirements_digest=digest,
                    score=fit.score,
                    reasoning=projection.value.reasoning,
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
                    model_id=projection.model_id,
                    template_version=projection.template_version,
                )
            )

    async def _log_estimate_agreement(self, owner_id: uuid.UUID, fits: list[FitView]) -> None:
        """How well the local estimate that chose the k agreed with the fits
        then scored, as a rank correlation (ADR 0027). Numbers only, no user
        data: the evidence for keeping the estimate, or going back to the
        analysis's order."""
        scored = {fit.role_id: fit.score for fit in fits}
        placements = await self._latest_placements(owner_id, await self._candidates(owner_id))
        pairs = [
            (placement.fit_estimate, scored[placement.role_id])
            for placement in placements.values()
            if placement.role_id in scored and placement.fit_estimate is not None
        ]
        if len(pairs) < 3:
            return
        log.info(
            "rolemap.estimate_agreement",
            roles=len(pairs),
            spearman=round(spearman([e for e, _ in pairs], [float(f) for _, f in pairs]), 3),
        )

    # -- postings of the user's own (Phase 8) ------------------------------

    async def estimate_own_posting(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        job_description: str,
    ) -> dict[str, Any]:
        """What adding this posting will cost, before it is added: reading its
        JD's requirements, then scoring the fit. Nothing else on it calls the
        AI."""
        name, company, description = _own_posting(title, company_name, job_description)
        extract = await self._gateway.estimate(
            owner_id,
            task="rolemap.extract",
            template=load_template("role_extraction", "v1"),
            inputs={"postings": _jd_block(name, company, description)},
            untrusted=frozenset({"postings"}),
        )
        fit = await self._estimate_fit(owner_id)
        return {
            "cost_usd": str(extract.cost_usd + fit.cost_usd),
            "model_id": extract.model_id,
            "rate_is_published": extract.rate_is_published and fit.rate_is_published,
        }

    async def estimate_rescore(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> dict[str, Any]:
        """What rescoring a posting of the user's own costs: the fit only, since
        its requirements are kept."""
        await self._market.private_posting(owner_id, private_job_posting_id)
        fit = await self._estimate_fit(owner_id)
        return {
            "cost_usd": str(fit.cost_usd),
            "model_id": fit.model_id,
            "rate_is_published": fit.rate_is_published,
        }

    async def add_own_posting(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        job_description: str,
    ) -> tuple[OwnPostingView, uuid.UUID]:
        """Store a posting the user brought, privately, and record the run that
        reads and scores it, at the cost they confirmed. Returns the posting
        and the run for the caller to queue. Its fit needs the user's
        strengths, so an analysis comes first."""
        name, company, description = _own_posting(title, company_name, job_description)
        await self._require_strengths(owner_id)
        pasted = await self._market.paste_job_description(
            owner_id, company_name=company or "", title=name, location=None, description=description
        )
        async with self._uow.for_owner(owner_id) as mine:
            run = await mine.evaluations.create(
                PostingEvaluation.requested(
                    owner_id=owner_id,
                    private_job_posting_id=pasted.id,
                    reads_requirements=True,
                    at=utcnow(),
                )
            )
        log.info("rolemap.own_posting_added", private_job_posting_id=str(pasted.id))
        return await self.own_posting(owner_id, pasted.id), run.id

    async def rescore_own_posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> tuple[OwnPostingView, uuid.UUID | None]:
        """Score a posting of the user's own again, against their latest
        strengths. Only when they ask: never after an analysis by itself. A run
        still going is returned as it is, with nothing to queue."""
        await self._market.private_posting(owner_id, private_job_posting_id)
        await self._require_strengths(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            latest = await _latest_evaluation(mine, private_job_posting_id)
            if latest is not None and latest.is_running:
                return await self.own_posting(owner_id, private_job_posting_id), None
            requirements = await mine.posting_requirements.get_count(
                PostingRequirementFilter(private_job_posting_id=private_job_posting_id)
            )
            run = await mine.evaluations.create(
                PostingEvaluation.requested(
                    owner_id=owner_id,
                    private_job_posting_id=private_job_posting_id,
                    # Requirements are read once; only a failed first read
                    # reads them again.
                    reads_requirements=requirements == 0,
                    at=utcnow(),
                )
            )
        return await self.own_posting(owner_id, private_job_posting_id), run.id

    async def evaluate_own_posting(self, owner_id: uuid.UUID, evaluation_id: uuid.UUID) -> None:
        """The worker job for one recorded run: read the JD's requirements when
        the run asks for it, score them against the user's strengths, and work
        out the posting's fit from that locally.

        An expected failure is recorded on the run and not raised: a retry
        would spend the key again. Anything else is recorded as ``internal``
        and re-raised for the log.
        """
        async with self._uow.for_owner(owner_id) as mine:
            run = await mine.evaluations.get(evaluation_id)
        if run is None:
            raise NotFoundError("posting evaluation not found", evaluation_id=str(evaluation_id))
        if not run.is_running:
            return
        try:
            posting = await self._market.private_posting(owner_id, run.private_job_posting_id)
            if run.reads_requirements:
                await self._read_own_requirements(owner_id, posting)
            strengths = await self._require_strengths(owner_id)
            source = await self._project_own(owner_id, strengths, posting)
            await self._store_posting_fit(owner_id, strengths, source)
        except DomainError as exc:
            log.warning("rolemap.own_posting_failed", code=str(exc.code))
            await self._finish_evaluation(
                owner_id, evaluation_id, failure=(str(exc.code), exc.message)
            )
            return
        except Exception:
            await self._finish_evaluation(
                owner_id,
                evaluation_id,
                failure=(
                    "internal",
                    "Scoring your posting stopped unexpectedly. Try again in a moment.",
                ),
            )
            raise
        await self._finish_evaluation(owner_id, evaluation_id, failure=None)

    async def own_postings(self, owner_id: uuid.UUID) -> list[OwnPostingView]:
        """The postings the user brought, newest first, each with its latest
        run and fit. One user's pasted JDs: a small set, read whole."""
        pasted = await self._market.private_postings(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            runs = await mine.evaluations.get_list(PostingEvaluationFilter())
            fits = await mine.posting_fits.get_list(
                PostingFitFilter(posting_keys=tuple(get_own_posting_key(p.id) for p in pasted))
                if pasted
                else PostingFitFilter(posting_keys=())
            )
        latest_assessment = await self._latest_assessment(owner_id)
        latest_run: dict[uuid.UUID, PostingEvaluation] = {}
        for run in runs:
            latest_run.setdefault(run.private_job_posting_id, run)
        latest_fit: dict[str, PostingFit] = {}
        for fit in fits:
            latest_fit.setdefault(fit.posting_key, fit)
        return [
            _own_posting_view(
                posting,
                latest_run.get(posting.id),
                latest_fit.get(get_own_posting_key(posting.id)),
                latest_assessment,
            )
            for posting in pasted
        ]

    async def own_posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> OwnPostingView:
        for found in await self.own_postings(owner_id):
            if found.private_job_posting_id == private_job_posting_id:
                return found
        raise NotFoundError("posting not found", private_job_posting_id=str(private_job_posting_id))

    async def own_posting_fit(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> PostingFitView | None:
        """The current fit to a posting of the user's own, or none before it is
        scored."""
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.posting_fits.get_list(
                PostingFitFilter(posting_keys=(get_own_posting_key(private_job_posting_id),)),
                page_size=1,
            )
        return _posting_fit_view(found[0]) if found else None

    async def remove_own_posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> None:
        """Delete a posting of the user's own, its JD with it. Plans and résumés
        aimed at it keep their snapshots."""
        await self._market.private_posting(owner_id, private_job_posting_id)
        key = get_own_posting_key(private_job_posting_id)
        async with self._uow.for_owner(owner_id) as mine:
            for fit in await mine.posting_fits.get_list(PostingFitFilter(posting_keys=(key,))):
                await mine.posting_fits.delete(fit.id)
            for source in await mine.posting_requirement_fits.get_list(
                PostingRequirementFitFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.posting_requirement_fits.delete(source.id)
            for requirement in await mine.posting_requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.posting_requirements.delete(requirement.id)
            for run in await mine.evaluations.get_list(
                PostingEvaluationFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.evaluations.delete(run.id)
        await self._market.delete_private_posting(owner_id, private_job_posting_id)
        log.info("rolemap.own_posting_removed", private_job_posting_id=str(private_job_posting_id))

    async def _estimate_fit(self, owner_id: uuid.UUID) -> Any:
        return await self._gateway.estimate(
            owner_id,
            task="rolemap.fit",
            template=_fit_template(),
            inputs=_worst_case_fit_inputs(),
            untrusted=frozenset({"requirements"}),
        )

    async def _require_strengths(self, owner_id: uuid.UUID) -> list[CandidateStrength]:
        strengths = await self._strengths(owner_id)
        if not strengths:
            raise ValidationError("run an analysis before scoring a posting of your own")
        return strengths

    async def _latest_assessment(self, owner_id: uuid.UUID) -> uuid.UUID | None:
        strengths = await self._strengths(owner_id)
        return strengths[0].assessment_id if strengths else None

    async def _read_own_requirements(self, owner_id: uuid.UUID, posting: PostingView) -> None:
        """What the JD asks for, on the user's key: one call. Replaces what an
        earlier, failed run may have left."""
        extracted = await self._gateway.run(
            owner_id,
            task="rolemap.extract",
            template=load_template("role_extraction", "v1"),
            inputs={
                "postings": _jd_block(posting.title, posting.company_name, posting.description)
            },
            output_schema=_RoleExtraction,
            untrusted=frozenset({"postings"}),
        )
        async with self._uow.for_owner(owner_id) as mine:
            for old in await mine.posting_requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=posting.id)
            ):
                await mine.posting_requirements.delete(old.id)
            for read in extracted.value.requirements:
                await mine.posting_requirements.create(
                    PostingRequirement(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        private_job_posting_id=posting.id,
                        statement=read.statement,
                        weight=read.weight,
                        expected_level=read.expected_level,
                    )
                )

    async def _project_own(
        self, owner_id: uuid.UUID, strengths: list[CandidateStrength], posting: PostingView
    ) -> PostingRequirementFit:
        """Map the posting's requirements onto the user's dimensions, with a
        target for each, on the user's key: one call, the projection a role's
        fit makes."""
        async with self._uow.for_owner(owner_id) as mine:
            read = await mine.posting_requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=posting.id)
            )
        if not read:
            raise ValidationError("no requirements could be read out of this job description")
        requirements = tuple(
            RequirementView(r.statement, r.weight, r.expected_level)
            for r in sorted(read, key=lambda r: (-r.weight, r.statement))
        )
        digest = _digest(requirements)
        async with self._uow.for_owner(owner_id) as mine:
            earlier = await mine.posting_requirement_fits.get_list(
                PostingRequirementFitFilter(private_job_posting_id=posting.id), page_size=1
            )
        # A rescore against the same scores and requirements would come out
        # the same: the posting's fit is worked out from the one there is.
        if earlier and earlier[0].is_current(
            assessment_id=strengths[0].assessment_id, requirements_digest=digest
        ):
            return earlier[0]
        known_keys = {s.dimension_key for s in strengths}
        projection = await self._gateway.run(
            owner_id,
            task="rolemap.fit",
            template=_fit_template(),
            inputs={
                "dimensions": _strengths_block(strengths),
                "role_name": posting.title,
                "requirements": _requirements_lines(requirements),
            },
            output_schema=_Projection,
            untrusted=frozenset({"requirements"}),
        )
        async with self._uow.for_owner(owner_id) as mine:
            return await mine.posting_requirement_fits.create(
                PostingRequirementFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    private_job_posting_id=posting.id,
                    assessment_id=strengths[0].assessment_id,
                    requirements=_requirement_dicts(requirements),
                    requirement_map=_requirement_map(projection.value, requirements, known_keys),
                    target_profile={
                        t.dimension_id: t.target
                        for t in projection.value.target_scores
                        if t.dimension_id in known_keys
                    },
                    reasoning=projection.value.reasoning,
                    model_id=projection.model_id,
                    template_version=projection.template_version,
                    requirements_digest=digest,
                )
            )

    async def _store_posting_fit(
        self,
        owner_id: uuid.UUID,
        strengths: list[CandidateStrength],
        source: PostingRequirementFit,
    ) -> None:
        """Work the posting's fit out from its AI fit, locally: no AI call."""
        user_scores = {s.dimension_key: s.score for s in strengths}
        found = get_posting_fit(
            requirements=source.requirements,
            requirement_map=source.requirement_map,
            target_profile=source.target_profile,
            user_scores=user_scores,
        )
        async with self._uow.for_owner(owner_id) as mine:
            await mine.posting_fits.create(
                PostingFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    posting_key=get_own_posting_key(source.private_job_posting_id),
                    basis=PostingFitBasis.OWN,
                    source_fit_id=source.id,
                    assessment_id=source.assessment_id,
                    score=found.score,
                    requirements=source.requirements,
                    requirement_map=dict(source.requirement_map),
                    target_profile=dict(source.target_profile),
                    gaps=_gap_dicts(found.gaps),
                    uncovered=tuple(
                        {"statement": u.statement, "weight": u.weight} for u in found.uncovered
                    ),
                )
            )

    async def _finish_evaluation(
        self,
        owner_id: uuid.UUID,
        evaluation_id: uuid.UUID,
        *,
        failure: tuple[str, str] | None,
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            run = await mine.evaluations.get(evaluation_id)
            if run is None or not run.is_running:
                return
            if failure is None:
                run.ready(utcnow())
            else:
                run.failed(code=failure[0], message=failure[1], at=utcnow())
            await mine.evaluations.update(run)

    # -- internals ----------------------------------------------------------

    async def _scope_vectors(
        self, owner_id: uuid.UUID
    ) -> list[tuple[str, PostingView, list[float]]]:
        """This user's postings, each with its embedding. No AI, no cost.

        Fewer than one role's worth of postings is no market to search, and
        comes back empty.
        """
        scope = await self._market.scope_with_vectors(owner_id, self._embedding_model)
        if len(scope) < MIN_POSTINGS_FOR_A_ROLE:
            return []

        missing = [(key, posting) for key, posting, vector in scope if vector is None]
        fresh: dict[str, list[float]] = {}
        if missing:
            # Postings the crawler has not embedded yet; embedding is local.
            texts = [
                "\n".join(
                    part for part in (p.title, p.title, p.location or "", p.description) if part
                )
                for _key, p in missing
            ]
            vectors = embed(texts, model_name=self._embedding_model)
            fresh = dict(zip((k for k, _ in missing), vectors, strict=True))
        return [
            (key, posting, vector if vector is not None else fresh[key])
            for key, posting, vector in scope
        ]

    async def _previous_members(self, owner_id: uuid.UUID) -> dict[str, set[str]]:
        """Every role's postings from the last run, retired ones included. One
        user's map, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            roles = await mine.roles.get_list(RoleFilter())
            if not roles:
                return {}
            members = await mine.members.get_list(
                RoleMemberFilter(role_ids=tuple(r.id for r in roles))
            )
        previous: dict[str, set[str]] = {}
        for member in members:
            previous.setdefault(str(member.role_id), set()).add(member.posting_key)
        return previous

    async def _keep_role(
        self, owner_id: uuid.UUID, *, role_id: uuid.UUID, postings: list[PostingView]
    ) -> bool:
        """Keep an already-analysed role on the map, refreshing only what needs
        no AI: its opening count and salary bands. ``False`` means there is no
        analysed role to keep, and its postings are analysed afresh."""
        bands = await self._salary_bands(owner_id, postings)
        async with self._uow.for_owner(owner_id) as mine:
            role = await mine.roles.get(role_id)
            if role is None:
                return False
            role.refresh_market(opening_count=len(postings), salary_bands=bands)
            await mine.roles.update(role)
        return True

    async def _store_role(
        self,
        owner_id: uuid.UUID,
        *,
        role_id: uuid.UUID,
        keys: set[str],
        postings: list[PostingView],
        extraction: _RoleExtraction,
        bar: HiringBar,
        bar_reasoning: str,
        model_id: str,
        template_version: str,
    ) -> None:
        bands = await self._salary_bands(owner_id, postings)

        async with self._uow.for_owner(owner_id) as mine:
            role = await mine.roles.get(role_id)
            is_new = role is None
            role = role or Role(id=role_id, owner_id=owner_id, name=extraction.name)
            role.analysed(
                name=extraction.name,
                is_coherent=extraction.is_coherent,
                opening_count=len(postings),
                bar=bar,
                bar_reasoning=bar_reasoning,
                salary_bands=bands,
                model_id=model_id,
                template_version=template_version,
            )
            if is_new:
                await mine.roles.create(role)
            else:
                await mine.roles.update(role)

            # A role's members and requirements are replaced wholesale by a
            # fresh analysis; a role holds a few dozen of each.
            for member in await mine.members.get_list(RoleMemberFilter(role_ids=(role_id,))):
                await mine.members.delete(member.id)
            for requirement in await mine.requirements.get_list(
                RoleRequirementFilter(role_ids=(role_id,))
            ):
                await mine.requirements.delete(requirement.id)

            for key in sorted(keys):
                await mine.members.create(
                    RoleMember(id=uuid.uuid4(), owner_id=owner_id, role_id=role_id, posting_key=key)
                )
            for extracted in extraction.requirements:
                await mine.requirements.create(
                    RoleRequirement(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        role_id=role_id,
                        statement=extracted.statement,
                        weight=extracted.weight,
                        expected_level=extracted.expected_level,
                    )
                )

            mine.record(
                RoleRequirementsChanged(
                    owner_id=owner_id,
                    role_id=role_id,
                    requirements=len(extraction.requirements),
                )
            )

    async def _salary_bands(
        self, owner_id: uuid.UUID, postings: list[PostingView]
    ) -> dict[str, Any]:
        """One band per market the user selected, not one number per role."""
        selected = await self._market.target_locations(owner_id)
        bands: dict[str, Any] = {}
        for market in selected or [""]:
            ranges = [
                (p.salary.min_amount, p.salary.max_amount, p.salary.currency)
                for p in postings
                if p.salary is not None and (not market or in_market(p.location, market))
            ]
            band = band_from(ranges)
            if band is not None:
                bands[market or "all"] = {
                    "low": band.low,
                    "mid": band.mid,
                    "high": band.high,
                    "currency": band.currency,
                    "sample_size": band.sample_size,
                    # A thin market shows a low-confidence band rather than
                    # hiding the role.
                    "is_confident": band.is_confident,
                }
        return bands

    async def _record_lineage(self, owner_id: uuid.UUID, reconciliation: Reconciliation) -> None:
        """Retire the roles no candidate kept, merged ones included, and record
        what became of them. A role retired by an earlier build is left alone:
        retiring it again would add another lineage entry every build."""
        async with self._uow.for_owner(owner_id) as mine:
            already_retired: set[str] = set()
            for retired in reconciliation.retired_role_ids:
                role = await mine.roles.get(uuid.UUID(retired))
                if role is None or role.retired_at is not None:
                    already_retired.add(retired)
                    continue
                role.retire(utcnow())
                await mine.roles.update(role)

            for entry in reconciliation.lineage:
                if entry.kind is RoleChange.RETIRED and entry.role_id in already_retired:
                    continue
                await mine.lineage.create(
                    LineageEntry(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        role_id=uuid.UUID(entry.role_id),
                        kind=entry.kind,
                        from_role_ids=tuple(entry.from_role_ids),
                    )
                )

            split_or_merged = tuple(
                e for e in reconciliation.lineage if e.kind in (RoleChange.SPLIT, RoleChange.MERGED)
            )
            if split_or_merged:
                mine.record(RoleSplitOrMerged(owner_id=owner_id, changes=split_or_merged))
            mine.record(RolesReclustered(owner_id=owner_id, roles=len(reconciliation.assignments)))


def _posting_key(posting: PostingView) -> str:
    """The key a posting is matched under (see ``MarketService.scope_with_vectors``)."""
    return str(posting.id)


def _jd_block(title: str, company_name: str | None, description: str) -> str:
    """A pasted JD as untrusted text, trimmed like a posting."""
    return (
        f"### {title} — {company_name or 'company not stated'} (the user's own JD)\n"
        f"{description[:MAX_DESCRIPTION_CHARS]}"
    )


def _prompt_length(posting: PostingView) -> int:
    """How much of a prompt this posting fills, as ``_postings_block`` trims it."""
    return (
        len(posting.title)
        + len(posting.company_name)
        + len(posting.location or "")
        + min(len(posting.description), MAX_DESCRIPTION_CHARS)
    )


def _postings_block(postings: list[PostingView]) -> str:
    """Untrusted posting text, trimmed so one role is one predictable call."""
    chunks = []
    for posting in postings[:MAX_POSTINGS_IN_A_PROMPT]:
        chunks.append(
            f"### {posting.title} — {posting.company_name}"
            f" ({posting.location or 'location not stated'})\n"
            f"{posting.description[:MAX_DESCRIPTION_CHARS]}"
        )
    return "\n\n".join(chunks)


def _first[T](items: list[T]) -> T | None:
    return items[0] if items else None


def _candidate_view(
    candidate: RoleCandidate, placement: CandidatePlacement | None
) -> RoleCandidateView:
    return RoleCandidateView(
        id=candidate.id,
        rank=candidate.rank,
        title=candidate.title,
        description=candidate.description,
        dimension_keys=candidate.dimension_keys,
        role_id=placement.role_id if placement is not None else None,
        opening_count=placement.opening_count if placement is not None else 0,
        fit_estimate=placement.fit_estimate if placement is not None else None,
        outcome=str(placement.outcome) if placement is not None else None,
    )


def _role_view(role: Role, requirements: list[RoleRequirement]) -> RoleView:
    return RoleView(
        id=role.id,
        name=role.name,
        hiring_bar=role.hiring_bar,
        bar_basis=role.bar_basis,
        bar_confidence=role.bar_confidence,
        bar_reasoning=role.bar_reasoning,
        opening_count=role.opening_count,
        salary_bands=dict(role.salary_bands),
        requirements=tuple(
            RequirementView(r.statement, r.weight, r.expected_level)
            for r in sorted(requirements, key=lambda r: (-r.weight, r.statement))
        ),
        is_coherent=role.is_coherent,
    )


def role_bar_is_estimate(role: RoleView) -> bool:
    """Estimated bubbles are drawn with a dashed outline."""
    return role.bar_basis == str(BarBasis.ESTIMATED)


def _build_view(build: BuildRun) -> BuildRunView:
    return BuildRunView(
        id=build.id,
        status=str(build.status),
        requested_at=build.requested_at,
        started_at=build.started_at,
        finished_at=build.finished_at,
        error_code=build.error_code,
        error_message=build.error_message,
        is_waiting_for_market=build.is_waiting_for_market,
        awaited_since=build.awaited_since,
        locations=build.locations,
        needed_source_ids=build.needed_source_ids,
        market_data_at=build.market_data_at,
    )


def _check_strengths(strengths: Sequence[StrengthInput]) -> None:
    """What an analysis hands over: at most ``MAX_STRENGTHS`` dimensions, each
    scored 0 to 100 with a confidence from 0 to 1."""
    if len(strengths) > MAX_STRENGTHS:
        raise ValidationError(
            f"an analysis hands over at most {MAX_STRENGTHS} dimensions",
            strengths=len(strengths),
        )
    for strength in strengths:
        if not 0 <= strength.score <= 100 or not 0.0 <= strength.confidence <= 1.0:
            raise ValidationError(
                "a dimension is scored 0 to 100 with a confidence from 0 to 1",
                dimension_key=strength.dimension_key,
            )


def _strengths_block(strengths: Sequence[CandidateStrength]) -> str:
    return "\n".join(
        f"- {s.dimension_key}: {s.name} — scored {s.score}/100 (confidence {s.confidence:.2f})"
        for s in strengths
    )


def _uncovered_from(
    projection: _Projection, requirements: tuple[RequirementView, ...], known_keys: set[str]
) -> list[UncoveredRequirement]:
    """Requirements that map to no dimension of this user's.

    Never dropped: no evidence at all is a different thing from a low score.
    """
    mapped = {m.requirement_statement for m in projection.mappings if m.dimension_id in known_keys}
    return [
        UncoveredRequirement(statement=r.statement, weight=r.weight)
        for r in {r.statement: r for r in requirements}.values()
        if r.statement not in mapped
    ]


def _worst_case_fit_inputs() -> dict[str, str]:
    """Inputs as large as a fit projection's can be, for pricing it before the
    dimensions or the roles exist."""
    return {
        "dimensions": "\n".join(
            f"- dimension-{i:02d}: {'x' * 60} — scored 100/100 (confidence 1.00)"
            for i in range(MAX_STRENGTHS)
        ),
        "role_name": "x" * MAX_ROLE_TITLE,
        "requirements": "\n".join(
            f"- {'x' * 160} (weight 1.0, expects senior)" for _ in range(MAX_ROLE_REQUIREMENTS)
        ),
    }


def _fit_view(fit: RoleFit) -> FitView:
    # Set by the database when the fit was stored.
    assert fit.created_at is not None, "a stored fit has a creation time"
    return FitView(
        role_id=fit.role_id,
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


def _own_posting(
    title: str, company_name: str | None, job_description: str
) -> tuple[str, str | None, str]:
    try:
        return parse_own_posting(
            title=title, company_name=company_name, job_description=job_description
        )
    except OwnPostingError as exc:
        raise ValidationError(str(exc)) from exc


async def _latest_evaluation(
    mine: OwnerRoleMap, private_job_posting_id: uuid.UUID
) -> PostingEvaluation | None:
    found = await mine.evaluations.get_list(
        PostingEvaluationFilter(private_job_posting_id=private_job_posting_id), page_size=1
    )
    return found[0] if found else None


def _requirements_lines(requirements: Sequence[RequirementView]) -> str:
    return "\n".join(
        f"- {r.statement} (weight {r.weight}, expects {r.expected_level})" for r in requirements
    )


def _requirement_dicts(requirements: Sequence[RequirementView]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"statement": r.statement, "weight": r.weight, "expected_level": r.expected_level}
        for r in requirements
    )


def _requirement_map(
    projection: _Projection, requirements: Sequence[RequirementView], known_keys: set[str]
) -> dict[str, str | None]:
    """Requirement statement -> the user's dimension it maps to, or None. A
    statement mapped more than once keeps a dimension the user has."""
    found: dict[str, str | None] = {r.statement: None for r in requirements}
    for mapping in projection.mappings:
        if mapping.requirement_statement in found and mapping.dimension_id in known_keys:
            found[mapping.requirement_statement] = mapping.dimension_id
    return found


def _gap_dicts(gaps: Sequence[SkillGap]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "dimension_key": gap.dimension_id,
            "user_score": gap.user_score,
            "target_score": gap.target_score,
            "delta": gap.delta,
        }
        for gap in gaps
    )


def _posting_fit_view(fit: PostingFit) -> PostingFitView:
    # Set by the database when the fit was stored.
    assert fit.created_at is not None, "a stored fit has a creation time"
    return PostingFitView(
        posting_key=fit.posting_key,
        basis=str(fit.basis),
        score=fit.score,
        gaps=fit.gaps,
        uncovered=fit.uncovered,
        requirements=tuple(
            RequirementView(r["statement"], r["weight"], r["expected_level"])
            for r in fit.requirements
        ),
        requirement_map=dict(fit.requirement_map),
        target_profile=dict(fit.target_profile),
        assessment_id=fit.assessment_id,
        created_at=fit.created_at,
    )


def _own_posting_view(
    posting: PostingView,
    run: PostingEvaluation | None,
    fit: PostingFit | None,
    latest_assessment: uuid.UUID | None,
) -> OwnPostingView:
    return OwnPostingView(
        private_job_posting_id=posting.id,
        title=posting.title,
        company_name=posting.company_name,
        status=str(run.status) if run is not None else None,
        error_code=run.error_code if run is not None else None,
        error_message=run.error_message if run is not None else None,
        fit=fit.score if fit is not None else None,
        is_stale=(
            fit is not None
            and latest_assessment is not None
            and fit.assessment_id != latest_assessment
        ),
        scored_at=fit.created_at if fit is not None else None,
    )


def _fit_template() -> PromptTemplate:
    """The fit projection prompt: every fit is scored with it, and its version
    is part of what a fit read."""
    return load_template("fit_projection", "v1")


def _digest(requirements: Sequence[RequirementView]) -> str:
    """What scoring these requirements reads, with today's fit prompt."""
    return get_requirements_digest(
        _requirement_dicts(requirements), template_version=_fit_template().version_id
    )
