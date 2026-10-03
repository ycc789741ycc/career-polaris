"""Targets: what a gap plan or a résumé is aimed at (domain decision 26, ADR 0022).

A Target is one of the user's Roles and optionally one opening in it, or a
posting of the user's own (Phase 8). This module resolves one through the
other components' public surfaces and freezes what it requires and how the
user measures up into a ``TargetSnapshot``, which the plan or résumé stores.

The role map picks a role and an opening. A posting of the user's own is
Target's (ADR 0033): a job the role map does not show, brought to the Advisor
by uploading its JD as a file, which the worker reads before anything else, or
by filling the role in by hand (ADR 0034). It is stored here and adding it
spends nothing: it is read and scored on the user's key when they set it as
the Advisor's target, and again only when its fit is out of date. No build
reads it. Its fit is scored with the role map's fit kit, so the fit rules stay
in one place (ADR 0028). Resolving a Target spends nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from advisor.assessment import AssessmentService
from advisor.market import PostingView
from advisor.rolemap import (
    FitView,
    PostingFitView,
    RequirementsReadView,
    RequirementView,
    RoleMapService,
    RoleView,
    StrengthsView,
    get_posting_fit_result,
    get_projection_digest,
)
from advisor.target.domain import (
    MAX_JOB_DESCRIPTION,
    DimensionGap,
    OwnerTarget,
    OwnPostingError,
    OwnPostingFit,
    OwnPostingFitFilter,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    Requirement,
    RequirementBasis,
    TargetError,
    TargetRef,
    TargetSnapshot,
    TargetUnitOfWork,
    UncoveredGap,
)
from kernel.clock import utcnow
from kernel.documents import ACCEPTED_TYPES, read_document_text
from kernel.errors import DomainError, NotFoundError, TargetUnusableError, ValidationError
from kernel.logging import get_logger
from kernel.storage import ObjectStore, object_key

__all__ = [
    "DimensionGap",
    "OwnPostingView",
    "TargetError",
    "TargetPreview",
    "TargetRef",
    "TargetService",
    "TargetSnapshot",
    "UncoveredGap",
    "requirements_block",
]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TargetPreview:
    """What pricing work on a Target needs, resolved without spending anything."""

    label: str
    snapshot: TargetSnapshot
    requirements_text: str


@dataclass(frozen=True, slots=True)
class OwnPostingView:
    """A posting the user brought themselves, to aim the Advisor at (Phase 8):
    how it came, where reading and scoring it stands, and its fit."""

    private_job_posting_id: uuid.UUID
    title: str
    company_name: str
    # `uploaded` with the file's name, `filled_in`, or `pasted` (no longer
    # taken, ADR 0034).
    source: str
    filename: str | None
    # Filled in with nothing listed: what it asks for is estimated.
    has_estimated_requirements: bool
    created_at: datetime | None
    # The latest run: `running`, `ready` or `failed`; none before any.
    status: str | None
    error_code: str | None
    error_message: str | None
    fit: int | None
    # Scored against an analysis older than the latest: worth rescoring.
    is_stale: bool
    scored_at: datetime | None


class TargetService:
    def __init__(
        self,
        uow: TargetUnitOfWork,
        *,
        assessment: AssessmentService,
        rolemap: RoleMapService,
        object_store: ObjectStore,
        upload_max_bytes: int,
        upload_max_pages: int,
    ) -> None:
        self._uow = uow
        self._assessment = assessment
        self._rolemap = rolemap
        self._store = object_store
        # How large an uploaded JD may be, and how many pages a PDF of one.
        self._upload_max_bytes = upload_max_bytes
        self._upload_max_pages = upload_max_pages

    async def snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        """Freeze the Target: what it requires and the user's fit to it.

        A posting of the user's own is measured against its JD's requirements
        and its own fit. A role is measured against its requirements across its
        openings. An opening is measured against its own fit, the role's
        requirements as it weighs them (Phase 8), or against its role's before
        a build has worked that out.
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
        opening_fit = (
            await self._rolemap.opening_fit(owner_id, role.id, opening.id) if opening else None
        )
        return await self._freeze(
            owner_id,
            ref,
            role=role,
            title=opening.title if opening else role.name,
            company=opening.company_name if opening else "",
            fit=opening_fit or fit,
            basis=RequirementBasis.OPENING if opening_fit else RequirementBasis.ROLE,
        )

    async def _own_posting_snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        posting = await self._posting(owner_id, _uuid(ref.private_job_posting_id or "", ref))
        fit = await self._own_posting_fit(owner_id, posting.id)
        if fit is None:
            raise TargetUnusableError(
                f"{posting.title} has not been scored against your profile yet; "
                "it is scored when you set it as your target",
                private_job_posting_id=ref.private_job_posting_id,
            )
        return await self._freeze(
            owner_id,
            ref,
            role=None,
            title=posting.title,
            company=posting.company_name or "",
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

    # -- postings of the user's own (Phase 8, ADR 0033) ----------------------

    async def add_own_posting(
        self,
        owner_id: uuid.UUID,
        *,
        title: str,
        company_name: str | None,
        requirements: tuple[str, ...],
    ) -> OwnPostingView:
        """Store a role the user filled in by hand, privately: a title, and
        what it asks for if they listed it. Spends nothing and reads nothing;
        that waits until it is set as the target (ADR 0034)."""
        try:
            posting = PrivateJobPosting.filled_in(
                owner_id=owner_id,
                title=title,
                company_name=company_name,
                requirements=requirements,
            )
        except OwnPostingError as exc:
            raise ValidationError(str(exc)) from exc
        async with self._uow.for_owner(owner_id) as mine:
            await mine.postings.create(posting)
        log.info("target.own_posting_added", private_job_posting_id=str(posting.id))
        return await self.own_posting(owner_id, posting.id)

    async def upload_own_posting(
        self,
        owner_id: uuid.UUID,
        *,
        title: str | None,
        company_name: str | None,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> OwnPostingView:
        """Store a JD the user uploaded as a file, privately. Without a title
        it is named after its file until it is read. Spends nothing: the file
        is only stored here, and read by the worker when the posting is set as
        the target (ADR 0034), never by a request handler."""
        if len(content) > self._upload_max_bytes:
            raise ValidationError(
                "this file is larger than we accept", limit_bytes=self._upload_max_bytes
            )
        if content_type not in ACCEPTED_TYPES:
            raise ValidationError(
                f"{content_type} is not a format we can read: upload a PDF, a Word file"
                " or plain text",
                content_type=content_type,
            )
        if not content.strip():
            raise ValidationError("this file is empty")
        key = object_key(owner_id, "ownpostings", str(uuid.uuid4()))
        try:
            posting = PrivateJobPosting.uploaded(
                owner_id=owner_id,
                title=title,
                company_name=company_name,
                filename=filename,
                content_type=content_type,
                storage_key=key,
            )
        except OwnPostingError as exc:
            raise ValidationError(str(exc)) from exc
        self._store.put(key, content, content_type)
        async with self._uow.for_owner(owner_id) as mine:
            await mine.postings.create(posting)
        log.info("target.own_posting_uploaded", private_job_posting_id=str(posting.id))
        return await self.own_posting(owner_id, posting.id)

    async def estimate_target(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> dict[str, Any]:
        """What setting a posting of the user's own as the target costs:
        nothing when its fit is current; otherwise reading what it asks for,
        if that has not been read yet, and scoring the fit. An unread file is
        priced as if it held the longest JD there may be: a ceiling."""
        posting = await self._posting(owner_id, private_job_posting_id)
        if _is_fit_current(await self.own_posting(owner_id, private_job_posting_id)):
            return {"cost_usd": "0", "model_id": None, "rate_is_published": True}
        async with self._uow.for_owner(owner_id) as mine:
            has_requirements = (
                await mine.requirements.get_count(
                    PostingRequirementFilter(private_job_posting_id=private_job_posting_id)
                )
                > 0
            )
        fit = await self._rolemap.estimate_projection(owner_id)
        if has_requirements:
            return {
                "cost_usd": str(fit.cost_usd),
                "model_id": fit.model_id,
                "rate_is_published": fit.rate_is_published,
            }
        if posting.has_estimated_requirements:
            read = await self._rolemap.estimate_inferred_requirements(
                owner_id, title=posting.title, company_name=posting.company_name
            )
        else:
            read = await self._rolemap.estimate_requirements(
                owner_id,
                title=posting.title,
                company_name=posting.company_name,
                job_description=posting.job_description or "x" * MAX_JOB_DESCRIPTION,
            )
        return {
            "cost_usd": str(read.cost_usd + fit.cost_usd),
            "model_id": read.model_id,
            "rate_is_published": read.rate_is_published and fit.rate_is_published,
        }

    async def set_as_target(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> tuple[OwnPostingView, uuid.UUID | None]:
        """Make a posting of the user's own ready to aim the Advisor at, at the
        cost they confirmed: record the run that reads what it asks for, if
        that has not been read, and scores the fit against their latest
        strengths. Returns the run for the caller to queue, or none when there
        is nothing to do: its fit is current, or a run is already going."""
        await self._posting(owner_id, private_job_posting_id)
        view = await self.own_posting(owner_id, private_job_posting_id)
        if view.status == "running" or _is_fit_current(view):
            return view, None
        await self._require_strengths(owner_id)
        async with self._uow.for_owner(owner_id) as mine:
            requirements = await mine.requirements.get_count(
                PostingRequirementFilter(private_job_posting_id=private_job_posting_id)
            )
            run = await mine.evaluations.create(
                PostingEvaluation.requested(
                    owner_id=owner_id,
                    private_job_posting_id=private_job_posting_id,
                    # Requirements are read once; a rescore keeps them.
                    reads_requirements=requirements == 0,
                    at=utcnow(),
                )
            )
        log.info("target.own_posting_targeted", private_job_posting_id=str(private_job_posting_id))
        return await self.own_posting(owner_id, private_job_posting_id), run.id

    async def evaluate_own_posting(self, owner_id: uuid.UUID, evaluation_id: uuid.UUID) -> None:
        """The worker job for one recorded run: read an uploaded file first,
        read what the posting asks for when the run asks for it, score that
        against the user's strengths, and work out the posting's fit from it
        locally.

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
            posting = await self._posting(owner_id, run.private_job_posting_id)
            if posting.is_waiting_for_its_file:
                posting = await self._read_file(owner_id, posting)
            if run.reads_requirements:
                await self._extract_requirements(owner_id, posting)
            strengths = await self._require_strengths(owner_id)
            source = await self._project(owner_id, strengths, posting)
            await self._create_fit(owner_id, strengths, source)
        except DomainError as exc:
            log.warning("target.own_posting_failed", code=str(exc.code))
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
        async with self._uow.for_owner(owner_id) as mine:
            postings = await mine.postings.get_list(PrivateJobPostingFilter())
            runs = await mine.evaluations.get_list(PostingEvaluationFilter())
            fits = await mine.fits.get_list(OwnPostingFitFilter())
        strengths = await self._rolemap.strengths(owner_id)
        latest_assessment = strengths.assessment_id if strengths is not None else None
        latest_run: dict[uuid.UUID, PostingEvaluation] = {}
        for run in runs:
            latest_run.setdefault(run.private_job_posting_id, run)
        latest_fit: dict[uuid.UUID, OwnPostingFit] = {}
        for fit in fits:
            latest_fit.setdefault(fit.private_job_posting_id, fit)
        return [
            _own_posting_view(
                posting,
                latest_run.get(posting.id),
                latest_fit.get(posting.id),
                latest_assessment,
            )
            for posting in postings
        ]

    async def own_posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> OwnPostingView:
        for found in await self.own_postings(owner_id):
            if found.private_job_posting_id == private_job_posting_id:
                return found
        raise NotFoundError("posting not found", private_job_posting_id=str(private_job_posting_id))

    async def remove_own_posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> None:
        """Delete a posting of the user's own, its JD and everything made of it,
        the file it came in included. Plans and résumés aimed at it keep their
        snapshots."""
        posting = await self._posting(owner_id, private_job_posting_id)
        async with self._uow.for_owner(owner_id) as mine:
            for fit in await mine.fits.get_list(
                OwnPostingFitFilter(private_job_posting_ids=(private_job_posting_id,))
            ):
                await mine.fits.delete(fit.id)
            for source in await mine.requirement_fits.get_list(
                PostingRequirementFitFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.requirement_fits.delete(source.id)
            for requirement in await mine.requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.requirements.delete(requirement.id)
            for run in await mine.evaluations.get_list(
                PostingEvaluationFilter(private_job_posting_id=private_job_posting_id)
            ):
                await mine.evaluations.delete(run.id)
            await mine.postings.delete(private_job_posting_id)
        if posting.storage_key is not None:
            self._store.delete(posting.storage_key)
        log.info("target.own_posting_removed", private_job_posting_id=str(private_job_posting_id))

    async def _posting(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> PrivateJobPosting:
        """One posting of the user's own. Another user's is simply not found: it
        is behind RLS."""
        async with self._uow.for_owner(owner_id) as mine:
            posting = await mine.postings.get(private_job_posting_id)
        if posting is None:
            raise NotFoundError(
                "posting not found", private_job_posting_id=str(private_job_posting_id)
            )
        return posting

    async def _read_file(
        self, owner_id: uuid.UUID, posting: PrivateJobPosting
    ) -> PrivateJobPosting:
        """The text of an uploaded JD becomes its JD; the file is then deleted.
        Worker only. A file that cannot be read fails the run, and is kept so
        the posting can be removed with it."""
        if posting.storage_key is None or posting.content_type is None:
            raise ValidationError("this posting has no file to read")
        key = posting.storage_key
        text, _pages = read_document_text(
            self._store.get(key),
            content_type=posting.content_type,
            max_pages=self._upload_max_pages,
        )
        try:
            posting.read(text)
        except OwnPostingError as exc:
            raise ValidationError(str(exc)) from exc
        async with self._uow.for_owner(owner_id) as mine:
            posting = await mine.postings.update(posting)
        self._store.delete(key)
        return posting

    async def _own_posting_fit(
        self, owner_id: uuid.UUID, private_job_posting_id: uuid.UUID
    ) -> PostingFitView | None:
        """The current fit to a posting of the user's own, or none before it is
        scored."""
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.fits.get_list(
                OwnPostingFitFilter(private_job_posting_ids=(private_job_posting_id,)),
                page_size=1,
            )
        return _posting_fit_view(found[0]) if found else None

    async def _require_strengths(self, owner_id: uuid.UUID) -> StrengthsView:
        strengths = await self._rolemap.strengths(owner_id)
        if strengths is None:
            raise ValidationError("run an analysis before scoring a posting of your own")
        return strengths

    async def _extract_requirements(self, owner_id: uuid.UUID, posting: PrivateJobPosting) -> None:
        """What the posting asks for, on the user's key: one call, reading its
        JD, or estimating from its title when the user listed nothing. An
        upload named after its file takes the name of the job it describes.
        Replaces what an earlier, failed run may have left."""
        found: RequirementsReadView
        if posting.has_estimated_requirements:
            found = await self._rolemap.infer_requirements(
                owner_id, title=posting.title, company_name=posting.company_name
            )
        else:
            found = await self._rolemap.extract_requirements(
                owner_id,
                title=posting.title,
                company_name=posting.company_name,
                job_description=posting.job_description or "",
            )
        read = found.requirements
        async with self._uow.for_owner(owner_id) as mine:
            if posting.has_placeholder_title:
                posting.update_title(found.name)
                await mine.postings.update(posting)
            for old in await mine.requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=posting.id)
            ):
                await mine.requirements.delete(old.id)
            for requirement in read:
                await mine.requirements.create(
                    PostingRequirement(
                        id=uuid.uuid4(),
                        owner_id=owner_id,
                        private_job_posting_id=posting.id,
                        statement=requirement.statement,
                        weight=requirement.weight,
                        expected_level=requirement.expected_level,
                    )
                )

    async def _project(
        self, owner_id: uuid.UUID, strengths: StrengthsView, posting: PrivateJobPosting
    ) -> PostingRequirementFit:
        """Map the posting's requirements onto the user's dimensions, with a
        target for each, on the user's key: one call, the projection a role's
        fit makes. A rescore against the same scores and requirements would
        come out the same, so the one there is is kept."""
        async with self._uow.for_owner(owner_id) as mine:
            read = await mine.requirements.get_list(
                PostingRequirementFilter(private_job_posting_id=posting.id)
            )
            earlier = await mine.requirement_fits.get_list(
                PostingRequirementFitFilter(private_job_posting_id=posting.id), page_size=1
            )
        if not read:
            raise ValidationError("no requirements could be read out of this job description")
        requirements = tuple(
            RequirementView(r.statement, r.weight, r.expected_level)
            for r in sorted(read, key=lambda r: (-r.weight, r.statement))
        )
        if earlier and earlier[0].is_current(
            assessment_id=strengths.assessment_id,
            requirements_digest=get_projection_digest(requirements),
        ):
            return earlier[0]
        projection = await self._rolemap.project_requirements(
            owner_id, title=posting.title, requirements=requirements
        )
        async with self._uow.for_owner(owner_id) as mine:
            return await mine.requirement_fits.create(
                PostingRequirementFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    private_job_posting_id=posting.id,
                    assessment_id=projection.assessment_id,
                    requirements=projection.requirements,
                    requirement_map=dict(projection.requirement_map),
                    target_profile=dict(projection.target_profile),
                    reasoning=projection.reasoning,
                    model_id=projection.model_id,
                    template_version=projection.template_version,
                    requirements_digest=projection.requirements_digest,
                )
            )

    async def _create_fit(
        self, owner_id: uuid.UUID, strengths: StrengthsView, source: PostingRequirementFit
    ) -> None:
        """Work the posting's fit out from its AI fit, locally: no AI call."""
        found = get_posting_fit_result(
            requirements=source.requirements,
            requirement_map=source.requirement_map,
            target_profile=source.target_profile,
            user_scores=strengths.scores,
        )
        async with self._uow.for_owner(owner_id) as mine:
            await mine.fits.create(
                OwnPostingFit(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    private_job_posting_id=source.private_job_posting_id,
                    source_fit_id=source.id,
                    assessment_id=source.assessment_id,
                    score=found.score,
                    requirements=source.requirements,
                    requirement_map=dict(source.requirement_map),
                    target_profile=dict(source.target_profile),
                    gaps=found.gaps,
                    uncovered=found.uncovered,
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

    # -- resolving -----------------------------------------------------------

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


def _is_fit_current(posting: OwnPostingView) -> bool:
    """Whether a posting's fit can be planned against as it is: scored, and
    against the user's latest strengths. Pure."""
    return posting.fit is not None and not posting.is_stale


async def _latest_evaluation(
    mine: OwnerTarget, private_job_posting_id: uuid.UUID
) -> PostingEvaluation | None:
    found = await mine.evaluations.get_list(
        PostingEvaluationFilter(private_job_posting_id=private_job_posting_id), page_size=1
    )
    return found[0] if found else None


def _posting_fit_view(fit: OwnPostingFit) -> PostingFitView:
    # Set by the database when the fit was stored.
    assert fit.created_at is not None, "a stored fit has a creation time"
    return PostingFitView(
        posting_key=str(fit.private_job_posting_id),
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
    posting: PrivateJobPosting,
    run: PostingEvaluation | None,
    fit: OwnPostingFit | None,
    latest_assessment: uuid.UUID | None,
) -> OwnPostingView:
    return OwnPostingView(
        private_job_posting_id=posting.id,
        title=posting.title,
        company_name=posting.company_name or "",
        source=str(posting.source),
        filename=posting.filename,
        has_estimated_requirements=posting.has_estimated_requirements,
        created_at=posting.created_at,
        status=str(run.status) if run is not None else None,
        error_code=run.error_code if run is not None else None,
        error_message=run.error_message if run is not None else None,
        fit=fit.score if fit is not None else None,
        is_stale=fit is not None and fit.is_stale(latest_assessment),
        scored_at=fit.created_at if fit is not None else None,
    )
