"""The role map: postings grouped into roles, per user, on the user's key.

The split that matters here is who pays for what. Clustering runs locally on
the platform — plain computation. The user's key is spent only on naming a
cluster, pulling its requirements out, and estimating its interview difficulty
(domain decision 7).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from advisor.market import MarketService, PostingView, band_from, in_market, names_every_word
from advisor.profile import ProfileService
from advisor.rolemap.domain import (
    MIN_POSTINGS_FOR_A_ROLE,
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
    RoleChange,
    RoleFilter,
    RoleMapUnitOfWork,
    RoleMember,
    RoleMemberFilter,
    RoleOrigin,
    RoleRequirement,
    RoleRequirementFilter,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    blend,
    max_role_count,
    rank_by_fit,
    reconcile,
)
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.clock import utcnow
from kernel.embeddings import cluster, embed
from kernel.errors import DomainError, NotFoundError, ValidationError
from kernel.logging import get_logger

__all__ = ["BuildRequestView", "BuildRunView", "RequirementView", "RoleMapService", "RoleView"]

log = get_logger(__name__)

# The user's key is spent per cluster, so a first run has a predictable cost.
MAX_POSTINGS_IN_A_PROMPT = 12
MAX_DESCRIPTION_CHARS = 4000


class _Requirement(BaseModel):
    statement: str
    weight: float = Field(ge=0.0, le=1.0)
    expected_level: str


class _RoleExtraction(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_coherent: bool = True
    requirements: list[_Requirement] = Field(min_length=1, max_length=20)


class _DifficultyEstimate(BaseModel):
    difficulty: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


@dataclass(frozen=True, slots=True)
class _Group:
    """One cluster of postings, before it is analysed into a role."""

    keys: set[str]
    postings: list[PostingView]
    vectors: list[list[float]]


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
        profile: ProfileService,
        gateway: AiGateway,
        embedding_model: str,
    ) -> None:
        self._uow = uow
        self._market = market
        self._profile = profile
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

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        """The most a role map can cost, before any money is spent.

        A ceiling, not a prediction: the api runs no embeddings or clustering,
        so it prices the largest number of clusters these postings could form,
        capped at the ten recommended roles, each sent with the costliest
        prompt they could fill.
        """
        postings = await self._market.postings_in_scope(owner_id)
        max_clusters = max_role_count(len(postings))
        if max_clusters == 0:
            return {"max_clusters": 0, "cost_usd": "0", "model_id": None}

        template = load_template("role_extraction", "v1")
        sample = _postings_block(sorted(postings, key=_prompt_length, reverse=True))
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.extract",
            template=template,
            inputs={"postings": sample},
            untrusted=frozenset({"postings"}),
        )
        # Two calls per cluster: extraction, then the difficulty estimate.
        total = estimate.cost_usd * max_clusters * 2
        return {
            "max_clusters": max_clusters,
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
        return roles

    async def fail_build(
        self, owner_id: uuid.UUID, build_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        """Close a build without a result. Also how ``advisor.activity`` gives
        up on a build whose worker never came back."""
        async with self._uow.for_owner(owner_id) as mine:
            failed = await mine.builds.get(build_id)
            if failed is None or not failed.is_open:
                return
            failed.failed(code=code, message=message, at=utcnow())
            await mine.builds.update(failed)

    async def recluster(self, owner_id: uuid.UUID) -> list[RoleView]:
        """Rebuild this user's role map.

        Role ids survive: a goal or a saved fit pointing at a role must still
        find it after a crawl changes the underlying postings.
        """
        found = await self._group_postings(owner_id)
        if found:
            await self._build_recommended(owner_id, found)
        else:
            log.info("rolemap.nothing_to_cluster", owner_id=str(owner_id))
        await self._build_custom(owner_id)
        return await self.roles(owner_id)

    async def _build_recommended(self, owner_id: uuid.UUID, found: list[_Group]) -> None:
        """The ten clusters closest to the profile, analysed on the user's key."""
        # Only the ten clusters closest to the profile are analysed on the
        # user's key; the rest are left out, so roles they held are retired below.
        keep = rank_by_fit(
            await self._profile_vectors(owner_id), [group.vectors for group in found]
        )
        groups = [found[index] for index in keep]
        log.info(
            "rolemap.selected",
            owner_id=str(owner_id),
            clusters_found=len(found),
            clusters_kept=len(groups),
        )

        previous = await self._previous_members(owner_id)
        reconciliation = reconcile(
            previous=previous,
            clusters=[group.keys for group in groups],
            new_id=lambda: str(uuid.uuid4()),
        )

        for index, group in enumerate(groups):
            role_id = uuid.UUID(reconciliation.assignments[index])
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
        user's key: two calls. ``block`` is the untrusted text read — the
        cluster's postings, or a custom role's JD."""
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

    async def _group_postings(self, owner_id: uuid.UUID) -> list[_Group]:
        """Cluster this user's postings locally. No AI, no cost."""
        scope = await self._market.scope_with_vectors(owner_id, self._embedding_model)
        if len(scope) < MIN_POSTINGS_FOR_A_ROLE:
            return []

        missing = [(key, posting) for key, posting, vector in scope if vector is None]
        if missing:
            # Postings the crawler has not embedded yet; embedding is local.
            texts = [
                "\n".join(
                    part for part in (p.title, p.title, p.location or "", p.description) if part
                )
                for _key, p in missing
            ]
            fresh = embed(texts, model_name=self._embedding_model)
            by_key = dict(zip((k for k, _ in missing), fresh, strict=True))
            scope = [
                (key, posting, vector if vector is not None else by_key[key])
                for key, posting, vector in scope
            ]

        keys = [key for key, _p, _v in scope]
        postings = [p for _k, p, _v in scope]
        vectors = [v for _k, _p, v in scope if v is not None]

        result = cluster(vectors, min_cluster_size=MIN_POSTINGS_FOR_A_ROLE)
        groups: list[_Group] = []
        for cluster_id in result.cluster_ids:
            members = result.members(cluster_id)
            groups.append(
                _Group(
                    keys={keys[i] for i in members},
                    postings=[postings[i] for i in members],
                    vectors=[vectors[i] for i in members],
                )
            )
        return groups

    async def _profile_vectors(self, owner_id: uuid.UUID) -> list[list[float]]:
        """The user's profile in the postings' embedding space: one vector per
        evidence fact and per position held. Local and platform-paid."""
        snapshot = await self._profile.snapshot(owner_id)
        texts = [e.fact for e in snapshot.evidence if e.fact.strip()]
        texts += [p.title for p in snapshot.positions if p.title.strip()]
        return embed(texts, model_name=self._embedding_model)

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
        analysed role to keep, and the cluster is analysed afresh."""
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
    """The key a posting is clustered under (see ``MarketService.scope_with_vectors``)."""
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
    """Untrusted posting text, trimmed so one cluster is one predictable call."""
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
