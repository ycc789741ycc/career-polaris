"""The role map: the roles the user's strengths point to, found on the market,
per user, on the user's key.

The analysis recommends candidate roles (ADR 0024); a build searches the
postings in the user's target locations for each and keeps the top k the
market has, k a setting (ADR 0029). The split that matters is who pays for what. Embedding and
matching run locally on the platform — plain computation. The user's key is
spent only on naming a role, pulling its requirements out, and estimating its
interview difficulty (domain decision 7).
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
    CandidateStrength,
    CandidateStrengthFilter,
    ClosingLifts,
    CustomRoleAdded,
    CustomRoleError,
    HiringBar,
    LineageEntry,
    MatchCandidate,
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
    RoleOrigin,
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
    keep_on_market,
    max_role_count,
    rank_matches,
    reconcile,
    spearman,
)
from kernel.ai_gateway import AiGateway
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
    """A recommended candidate and what the last build made of it: the role it
    became, or none when the user's target locations lack openings for it."""

    id: uuid.UUID
    rank: int
    title: str
    description: str
    dimension_keys: tuple[str, ...]
    role_id: uuid.UUID | None
    opening_count: int
    # The local estimate that chose the k (ADR 0027); never a fit.
    fit_estimate: float | None = None


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
    # `recommended` or `custom` (ADR 0021); a custom role is drawn as "yours".
    origin: str = str(RoleOrigin.RECOMMENDED)
    company_name: str | None = None
    private_posting_id: uuid.UUID | None = None

    @property
    def is_custom(self) -> bool:
        return self.origin == str(RoleOrigin.CUSTOM)


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
        return [_candidate_view(c) for c in stored]

    async def candidates(self, owner_id: uuid.UUID) -> list[RoleCandidateView]:
        """The latest analysis's candidates, in its order, each with the role
        the last build made of it, if any."""
        return [_candidate_view(c) for c in await self._candidates(owner_id)]

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
        searches in the user's places, the baseline boards, and the custom
        roles' companies' boards. Only titles, places and company ids cross."""
        titles = [candidate.title for candidate in await self._candidates(owner_id)]
        places = await self._market.target_locations(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            custom = await mine.roles.get_list(
                RoleFilter(is_retired=False, origin=RoleOrigin.CUSTOM)
            )
        company_ids = [
            await self._market.company_named(role.company_name)
            for role in custom
            if role.company_name
        ]
        request = await self._market.request_sources(
            titles=titles, places=places, company_ids=company_ids
        )
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
            roles = await self.recluster(owner_id)
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

    async def recluster(self, owner_id: uuid.UUID) -> list[RoleView]:
        """Rebuild this user's role map from the latest analysis's candidates.

        Role ids survive: a goal or a saved fit pointing at a role must still
        find it after a crawl changes the underlying postings. With no
        candidates yet — no analysis has succeeded — only custom roles are
        placed, so nothing is spent on a map the user never priced.
        """
        candidates = await self._candidates(owner_id)
        if candidates:
            await self._build_recommended(owner_id, candidates)
        else:
            log.info("rolemap.no_candidates", owner_id=str(owner_id))
        await self._build_custom(owner_id)
        return await self.roles(owner_id)

    async def _build_recommended(
        self, owner_id: uuid.UUID, candidates: list[RoleCandidate]
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
            candidates,
            placed=placed,
            counts=counts,
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
        candidates: list[RoleCandidate],
        *,
        placed: dict[uuid.UUID, uuid.UUID],
        counts: dict[uuid.UUID, int],
        estimates: dict[uuid.UUID, float] | None = None,
    ) -> None:
        """Record what the build made of each candidate: its role, or none.

        An analysis that finished during the build has replaced the set; its
        candidates wait for the build that follows it, so the ones this build
        read and no longer exist are skipped.
        """
        async with self._uow.for_owner(owner_id) as mine:
            for read in candidates:
                candidate = await mine.candidates.get(read.id)
                if candidate is None:
                    continue
                role_id = placed.get(candidate.id)
                estimate = (estimates or {}).get(candidate.id)
                if role_id is None:
                    candidate.unplaced(
                        opening_count=counts.get(candidate.id, 0), fit_estimate=estimate
                    )
                else:
                    candidate.placed(
                        role_id=role_id, opening_count=counts[candidate.id], fit_estimate=estimate
                    )
                await mine.candidates.update(candidate)

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
        user's key: two calls. ``block`` is the untrusted text read — a
        candidate's openings, or a custom role's JD."""
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
        self, owner_id: uuid.UUID, *, recommended: int | None = None, extra_roles: int = 0
    ) -> dict[str, Any]:
        """The most scoring a build's fits can cost: one projection per role the
        map will hold — ``recommended`` roles (by default the ones on the map
        now), the user's own, and ``extra_roles`` about to be added — each with
        the most dimensions and requirements there can be. A ceiling, since
        nothing is known about the roles yet."""
        live = await self.roles(owner_id)
        custom = sum(1 for role in live if role.is_custom)
        if recommended is None:
            recommended = len(live) - custom
        roles = min(recommended, self._top_k) + custom + extra_roles
        if roles == 0:
            return {"cost_usd": "0", "roles": 0, "rate_is_published": True}
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.fit",
            template=load_template("fit_projection", "v1"),
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

        for role in roles:
            if not role.requirements:
                continue
            await self._project(owner_id, strengths, role)

        async with self._uow.for_owner(owner_id) as mine:
            mine.record(RoleFitsComputed(owner_id=owner_id, roles=len(roles)))
        fits = await self.fits(owner_id)
        await self._log_estimate_agreement(owner_id, fits)
        return fits

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

        Ranked by the role's current fit; no AI runs here. A custom role's
        private JD is not an opening: only shared postings are listed. An
        opening inside two roles (a custom role's title can match a
        recommended role's posting) is listed under each, as each role's
        bubble counts it.
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
            ranked = rank_matches(candidates, limit=limit)
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
        self, owner_id: uuid.UUID, strengths: list[CandidateStrength], role: RoleView
    ) -> None:
        """Map a role's requirements onto the user's dimensions, and store the
        fit."""
        user_scores = {s.dimension_key: s.score for s in strengths}
        known_keys = set(user_scores)
        requirements = role.requirements
        projection = await self._gateway.run(
            owner_id,
            task="rolemap.fit",
            template=load_template("fit_projection", "v1"),
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
        pairs = [
            (candidate.fit_estimate, scored[candidate.role_id])
            for candidate in await self._candidates(owner_id)
            if candidate.role_id in scored and candidate.fit_estimate is not None
        ]
        if len(pairs) < 3:
            return
        log.info(
            "rolemap.estimate_agreement",
            roles=len(pairs),
            spearman=round(spearman([e for e, _ in pairs], [float(f) for _, f in pairs]), 3),
        )

    # -- custom roles (ADR 0021) ---------------------------------------------

    async def add_custom_role(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        private_posting_id: uuid.UUID | None,
    ) -> RoleView:
        """A role the user named, placed beside the k. It is analysed by the
        next build, whose cost the user confirmed when adding it."""
        try:
            role = Role.custom(
                owner_id=owner_id,
                title=title,
                company_name=company_name,
                private_posting_id=private_posting_id,
            )
        except CustomRoleError as exc:
            raise ValidationError(str(exc)) from exc
        async with self._uow.for_owner(owner_id) as mine:
            created = await mine.roles.create(role)
            mine.record(
                CustomRoleAdded(
                    owner_id=owner_id, role_id=created.id, company_name=created.company_name
                )
            )
        log.info("rolemap.custom_role_added", role_id=str(created.id))
        return _role_view(created, [])

    async def remove_custom_role(self, owner_id: uuid.UUID, role_id: uuid.UUID) -> None:
        """Take a custom role off the map. It is retired, not deleted, so plans
        and résumés aimed at it keep their snapshots, like any retired role.
        Idempotent; a recommended role is not the user's to remove."""
        async with self._uow.for_owner(owner_id) as mine:
            role = await mine.roles.get(role_id)
            if role is None or not role.is_custom:
                raise NotFoundError("custom role not found", role_id=str(role_id))
            if role.retired_at is None:
                role.retire(utcnow())
                await mine.roles.update(role)

    async def estimate_custom_role(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        job_description: str | None,
    ) -> dict[str, Any]:
        """What adding this role will cost, before it is added: its two calls,
        read from the JD when there is one, else from the postings it matches."""
        try:
            Role.custom(
                owner_id=owner_id, title=title, company_name=company_name, private_posting_id=None
            )
        except CustomRoleError as exc:
            raise ValidationError(str(exc)) from exc
        matches = _custom_matches(
            title, company_name, await self._market.postings_in_scope(owner_id)
        )
        jd = (job_description or "").strip()
        if not jd and not matches:
            return {"matches": 0, "cost_usd": "0", "model_id": None}
        block = _jd_block(title, company_name, jd) if jd else _postings_block(matches)
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.extract",
            template=load_template("role_extraction", "v1"),
            inputs={"postings": block},
            untrusted=frozenset({"postings"}),
        )
        return {
            "matches": len(matches),
            "cost_usd": str(estimate.cost_usd * 2),
            "model_id": estimate.model_id,
            "rate_is_published": estimate.rate_is_published,
        }

    async def _build_custom(self, owner_id: uuid.UUID) -> None:
        """Place each custom role: match the postings in scope by title words,
        narrowed to its company, and read its requirements from its JD when it
        has one, else from those matches. Unchanged roles cost nothing."""
        async with self._uow.for_owner(owner_id) as mine:
            custom = await mine.roles.get_list(
                RoleFilter(is_retired=False, origin=RoleOrigin.CUSTOM)
            )
            members = (
                await mine.members.get_list(
                    RoleMemberFilter(role_ids=tuple(role.id for role in custom))
                )
                if custom
                else []
            )
        if not custom:
            return
        previous: dict[uuid.UUID, set[str]] = {}
        for member in members:
            previous.setdefault(member.role_id, set()).add(member.posting_key)
        in_scope = await self._market.postings_in_scope(owner_id)

        for role in custom:
            matches = _custom_matches(role.name, role.company_name, in_scope)
            keys = {_posting_key(p) for p in matches}
            unchanged = previous.get(role.id, set()) == keys and role.model_id is not None
            if unchanged and await self._keep_role(owner_id, role_id=role.id, postings=matches):
                continue
            jd = await self._custom_jd(owner_id, role)
            if jd is None and not matches:
                # Nothing to read requirements from: on the map, unscored.
                await self._keep_role(owner_id, role_id=role.id, postings=[])
                continue
            await self._analyse(
                owner_id,
                role_id=role.id,
                keys=keys,
                postings=matches,
                block=(
                    _jd_block(role.name, role.company_name, jd.description)
                    if jd is not None
                    else _postings_block(matches)
                ),
            )

    async def _custom_jd(self, owner_id: uuid.UUID, role: Role) -> PostingView | None:
        if role.private_posting_id is None:
            return None
        try:
            return await self._market.private_posting(owner_id, role.private_posting_id)
        except NotFoundError:
            return None

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
        """Every recommended role's postings from the last run, retired ones
        included. Custom roles are left out, so reconciliation can never retire
        one (ADR 0021). One user's map, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            recommended = await mine.roles.get_list(RoleFilter(origin=RoleOrigin.RECOMMENDED))
            if not recommended:
                return {}
            members = await mine.members.get_list(
                RoleMemberFilter(role_ids=tuple(r.id for r in recommended))
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


def _custom_matches(
    title: str, company_name: str | None, postings: list[PostingView]
) -> list[PostingView]:
    """The postings a custom role takes in: every word of its title in theirs,
    and every word of its company in theirs when one was named. The same word
    rule as a location in a target location."""
    return [
        p
        for p in postings
        if names_every_word(p.title, title)
        and (not company_name or names_every_word(p.company_name, company_name))
    ]


def _jd_block(title: str, company_name: str | None, description: str) -> str:
    """A custom role's pasted JD as untrusted text, trimmed like a posting."""
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


def _candidate_view(candidate: RoleCandidate) -> RoleCandidateView:
    return RoleCandidateView(
        id=candidate.id,
        rank=candidate.rank,
        title=candidate.title,
        description=candidate.description,
        dimension_keys=candidate.dimension_keys,
        role_id=candidate.role_id,
        opening_count=candidate.opening_count,
        fit_estimate=candidate.fit_estimate,
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
        origin=str(role.origin),
        company_name=role.company_name,
        private_posting_id=role.private_posting_id,
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
