"""The role map: the roles the user's strengths point to, found on the market,
per user, on the user's key.

The analysis recommends candidate roles (ADR 0024); a build searches the
postings in the user's target locations for each and keeps the first ten the
market has. The split that matters is who pays for what. Embedding and
matching run locally on the platform — plain computation. The user's key is
spent only on naming a role, pulling its requirements out, and estimating its
interview difficulty (domain decision 7).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from advisor.market import MarketService, PostingView, band_from, in_market, names_every_word
from advisor.rolemap.domain import (
    CANDIDATE_ROLE_COUNT,
    MAX_ROLE_REQUIREMENTS,
    MIN_POSTINGS_FOR_A_ROLE,
    RECOMMENDED_ROLE_COUNT,
    BarBasis,
    BuildRun,
    BuildRunFilter,
    BuildRunStatus,
    CustomRoleAdded,
    CustomRoleError,
    HiringBar,
    LineageEntry,
    Reconciliation,
    Role,
    RoleCandidate,
    RoleCandidateFilter,
    RoleChange,
    RoleFilter,
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
    assign_postings,
    blend,
    keep_on_market,
    max_role_count,
    reconcile,
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
    "RequirementView",
    "RoleCandidateView",
    "RoleMapService",
    "RoleView",
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


@dataclass(frozen=True, slots=True)
class RequirementView:
    statement: str
    weight: float
    expected_level: str


@dataclass(frozen=True, slots=True)
class RoleView:
    """One bubble. X is the hiring bar, Y is salary; size is fit, which lives
    in ``assessment`` because it is a property of the User x Role pair."""

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

    @property
    def is_open(self) -> bool:
        return self.status in (BuildRunStatus.WAITING, BuildRunStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class BuildRequestView:
    """What asking for a build did. ``should_queue`` is true only when this
    request started a build, so the caller queues it exactly once."""

    build: BuildRunView
    should_queue: bool


class RoleMapService:
    def __init__(
        self,
        uow: RoleMapUnitOfWork,
        *,
        market: MarketService,
        gateway: AiGateway,
        embedding_model: str,
    ) -> None:
        self._uow = uow
        self._market = market
        self._gateway = gateway
        self._embedding_model = embedding_model

    async def roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        """The live roles, newest first, each with its requirements, weightiest
        first. One user's map: ten roles and their own, read whole."""
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

    # -- candidates (ADR 0024) -----------------------------------------------

    async def replace_candidates(
        self,
        owner_id: uuid.UUID,
        assessment_id: uuid.UUID,
        candidates: Sequence[CandidateInput],
    ) -> list[RoleCandidateView]:
        """The roles an analysis recommended, replacing the last analysis's.

        Called by ``assessment`` once its scores are stored; the next build
        searches the market for these. At most ``CANDIDATE_ROLE_COUNT``, in the
        analysis's order.
        """
        if len(candidates) > CANDIDATE_ROLE_COUNT:
            raise ValidationError(
                f"an analysis recommends at most {CANDIDATE_ROLE_COUNT} roles",
                candidates=len(candidates),
            )
        async with self._uow.for_owner(owner_id) as mine:
            for previous in await mine.candidates.get_list(RoleCandidateFilter()):
                await mine.candidates.delete(previous.id)
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
        for one role at most, capped at the ten recommended roles, each sent
        with the costliest prompt they could fill.
        """
        postings = await self._market.postings_in_scope(owner_id)
        max_roles = max_role_count(len(postings))
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
        """Record a build, running now or waiting for an analysis.

        One build is open at a time: asking again while one is running returns
        it, which is what turns a crawl's stream of ``PostingsChanged`` into a
        single rebuild. A waiting build is started when ``wait`` is false.
        Whether to wait is ``advisor.activity``'s rule, not this component's.
        """
        now = utcnow()
        async with self._uow.for_owner(owner_id) as mine:
            open_builds = await mine.builds.get_list(
                BuildRunFilter(statuses=(BuildRunStatus.WAITING, BuildRunStatus.RUNNING)),
                page_size=1,
            )
            if open_builds:
                current = open_builds[0]
                if current.is_waiting and not wait:
                    current.start(now)
                    await mine.builds.update(current)
                    return BuildRequestView(_build_view(current), should_queue=True)
                return BuildRequestView(_build_view(current), should_queue=False)
            created = await mine.builds.create(
                BuildRun.requested(owner_id=owner_id, at=now, wait=wait)
            )
        log.info("rolemap.build_requested", build_id=str(created.id), waiting=wait)
        return BuildRequestView(_build_view(created), should_queue=not wait)

    async def start_waiting(self, owner_id: uuid.UUID) -> BuildRunView | None:
        """Start the build that was waiting, if any; the caller queues it."""
        async with self._uow.for_owner(owner_id) as mine:
            waiting = await mine.builds.get_list(
                BuildRunFilter(statuses=(BuildRunStatus.WAITING,)), page_size=1
            )
            if not waiting:
                return None
            waiting[0].start(utcnow())
            started = await mine.builds.update(waiting[0])
        log.info("rolemap.build_started", build_id=str(started.id))
        return _build_view(started)

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

        async with self._uow.for_owner(owner_id) as mine:
            done = await mine.builds.get(build_id)
            if done is not None and done.is_running:
                done.ready(utcnow())
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
        """The first ten candidates the market has, analysed on the user's key.

        Candidates the market lacks are left unplaced, and roles that no longer
        come from a kept candidate are retired by reconciliation.
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
        )
        members: list[list[int]] = [[] for _ in candidates]
        for posting_index, candidate_index in enumerate(assigned):
            if candidate_index is not None:
                members[candidate_index].append(posting_index)
        counts = {c.id: len(members[i]) for i, c in enumerate(candidates)}
        keep = keep_on_market([len(m) for m in members], limit=RECOMMENDED_ROLE_COUNT)
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
            candidates_kept=len(groups),
            postings_in_scope=len(scope),
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
        await self._place_candidates(owner_id, candidates, placed=placed, counts=counts)

    async def _place_candidates(
        self,
        owner_id: uuid.UUID,
        candidates: list[RoleCandidate],
        *,
        placed: dict[uuid.UUID, uuid.UUID],
        counts: dict[uuid.UUID, int],
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
                if role_id is None:
                    candidate.unplaced(opening_count=counts.get(candidate.id, 0))
                else:
                    candidate.placed(role_id=role_id, opening_count=counts[candidate.id])
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

    # -- custom roles (ADR 0021) ---------------------------------------------

    async def add_custom_role(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        private_posting_id: uuid.UUID | None,
    ) -> RoleView:
        """A role the user named, placed beside the ten. It is analysed by the
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
        async with self._uow.for_owner(owner_id) as mine:
            for entry in reconciliation.lineage:
                await mine.lineage.create(
                    LineageEntry(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        role_id=uuid.UUID(entry.role_id),
                        kind=entry.kind,
                        from_role_ids=tuple(entry.from_role_ids),
                    )
                )
            for retired in reconciliation.retired_role_ids:
                role = await mine.roles.get(uuid.UUID(retired))
                if role is not None:
                    role.retire(utcnow())
                    await mine.roles.update(role)

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
    )
