"""Target's use cases for postings of the user's own, against in-memory
storage: what they store, with no database and no model. Adding one spends
nothing; setting it as the target reads and scores it (ADR 0034). The fit is
scored with the role map's fit kit, over the role map's own in-memory
storage."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from typing import Any

import pytest

from advisor.rolemap import RoleMapService, StrengthInput
from advisor.rolemap.service import _Projection, _RoleExtraction
from advisor.target import TargetRef, TargetService
from advisor.target.domain import RequirementBasis
from kernel.errors import BudgetExceededError, NotFoundError, ValidationError
from tests.unit.advisor.rolemap.fakes import FakeMarket, FakeRoleMapUnitOfWork
from tests.unit.advisor.target.fakes import FakeObjectStore, FakeTargetUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Reply:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.model_id = "claude-opus-5"
        self.template_version = "v1"


class _Estimated:
    cost_usd = Decimal("0.10")
    model_id = "claude-opus-5"
    rate_is_published = True


class OwnPostingGateway:
    """Reads a JD's requirements, then maps them: ``skill 0.9`` onto
    ``backend``, wanted at ``target``, and ``skill 0.4`` onto nothing the user
    has. Records each call's task. ``fails`` makes the named task fail."""

    def __init__(self, target: int = 80, *, fails: str | None = None) -> None:
        self.target = target
        self.fails = fails
        self.tasks: list[str] = []
        self.templates: list[str] = []
        self.shown: list[dict[str, str]] = []

    async def run(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: Any,
        inputs: dict[str, str],
        **_: Any,
    ):
        self.tasks.append(task)
        self.templates.append(template.version_id)
        self.shown.append(inputs)
        if task == self.fails:
            raise BudgetExceededError("over the monthly budget")
        if task == "rolemap.extract":
            return _Reply(
                _RoleExtraction.model_validate(
                    {
                        "name": "Principal Engineer",
                        "requirements": [
                            {"statement": f"skill {w}", "weight": w, "expected_level": "senior"}
                            for w in (0.4, 0.9)
                        ],
                    }
                )
            )
        return _Reply(
            _Projection.model_validate(
                {
                    "mappings": [
                        {"requirement_statement": "skill 0.9", "dimension_id": "backend"},
                        {"requirement_statement": "skill 0.4", "dimension_id": "nowhere"},
                    ],
                    "target_scores": [{"dimension_id": "backend", "target": self.target}],
                    "reasoning": "Close on services.",
                }
            )
        )

    async def estimate(self, owner_id: uuid.UUID, *, template: Any, **_: Any) -> _Estimated:
        self.templates.append(f"estimate:{template.version_id}")
        return _Estimated()


class NoAssessment:
    """The analysis's dimension names: none, so a snapshot keeps the keys."""

    async def latest(self, owner_id: uuid.UUID) -> None:
        return None


def _target(
    uow: FakeTargetUnitOfWork, rolemap: RoleMapService, store: FakeObjectStore | None = None
) -> TargetService:
    return TargetService(
        uow,
        assessment=NoAssessment(),  # type: ignore[arg-type]
        rolemap=rolemap,
        object_store=store or FakeObjectStore(),  # type: ignore[arg-type]
        upload_max_bytes=1_000,
        upload_max_pages=2,
    )


def _services(
    gateway: Any = None, store: FakeObjectStore | None = None
) -> tuple[TargetService, RoleMapService, FakeTargetUnitOfWork, FakeRoleMapUnitOfWork]:
    rolemap_uow = FakeRoleMapUnitOfWork()
    if gateway is None:
        gateway = OwnPostingGateway()
    rolemap = RoleMapService(
        rolemap_uow,
        market=FakeMarket(),  # type: ignore[arg-type]
        gateway=gateway,
        embedding_model="test-model",
        top_k=10,
        candidate_count=20,
    )
    uow = FakeTargetUnitOfWork()
    return _target(uow, rolemap, store), rolemap, uow, rolemap_uow


async def _with_strengths(rolemap: RoleMapService, *, backend: int = 60) -> uuid.UUID:
    assessment_id = uuid.uuid4()
    await rolemap.replace_candidates(
        OWNER,
        assessment_id,
        [],
        strengths=[StrengthInput("backend", "Backend", "Built services.", backend, 0.9)],
    )
    return assessment_id


async def _add_own(
    target: TargetService, requirements: tuple[str, ...] = ("Own the ledger", "Lead incidents")
) -> uuid.UUID:
    posting = await target.add_own_posting(
        OWNER,
        title=" Staff Engineer ",
        company_name=" Northwind ",
        requirements=requirements,
    )
    return posting.private_job_posting_id


async def _target_run(target: TargetService, posting_id: uuid.UUID) -> uuid.UUID:
    """Set it as the target, and the run that reads and scores it."""
    _posting, run_id = await target.set_as_target(OWNER, posting_id)
    assert run_id is not None
    return run_id


async def _scored(target: TargetService) -> uuid.UUID:
    posting_id = await _add_own(target)
    await target.evaluate_own_posting(OWNER, await _target_run(target, posting_id))
    return posting_id


async def test_a_role_filled_in_is_stored_privately_and_spends_nothing() -> None:
    gateway = OwnPostingGateway()
    target, rolemap, uow, rolemap_uow = _services(gateway)

    posting = await target.add_own_posting(
        OWNER,
        title=" Staff Engineer ",
        company_name=" Northwind ",
        requirements=(" Own the ledger ", "", "Lead incidents"),
    )

    assert (posting.title, posting.company_name, posting.source, posting.status) == (
        "Staff Engineer",
        "Northwind",
        "filled_in",
        None,
    )
    assert posting.fit is None and not posting.has_estimated_requirements
    stored = uow.store.postings[posting.private_job_posting_id]
    assert stored.job_description == "- Own the ledger\n- Lead incidents"
    # No analysis needed to add one, nothing queued, nothing called.
    assert uow.store.evaluations == {} and gateway.tasks == []
    # Never on the map, and nothing built.
    assert await rolemap.roles(OWNER) == [] and rolemap_uow.store.builds == {}


async def test_a_role_filled_in_with_nothing_listed_has_estimated_requirements() -> None:
    target, _rolemap, uow, _ = _services()

    posting = await target.add_own_posting(
        OWNER, title="Platform Lead", company_name=None, requirements=()
    )

    assert posting.has_estimated_requirements and posting.company_name == ""
    assert uow.store.postings[posting.private_job_posting_id].job_description is None


@pytest.mark.parametrize(
    ("title", "requirements"),
    [("  ", ()), ("x" * 256, ()), ("Staff", ("x" * 501,)), ("Staff", ("r",) * 31)],
)
async def test_a_role_filled_in_needs_a_title_and_short_requirements(
    title: str, requirements: tuple[str, ...]
) -> None:
    target, _rolemap, uow, _ = _services()

    with pytest.raises(ValidationError):
        await target.add_own_posting(
            OWNER, title=title, company_name=None, requirements=requirements
        )
    assert uow.store.postings == {}


async def test_setting_one_as_the_target_needs_an_analysis_first() -> None:
    target, _rolemap, uow, _ = _services()
    posting_id = await _add_own(target)

    with pytest.raises(ValidationError):
        await target.set_as_target(OWNER, posting_id)
    assert uow.store.evaluations == {}


async def test_scoring_a_posting_reads_its_jd_then_works_its_fit_out_locally() -> None:
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway)
    assessment_id = await _with_strengths(rolemap)
    posting_id = await _add_own(target)
    run_id = await _target_run(target, posting_id)

    await target.evaluate_own_posting(OWNER, run_id)

    # Two calls, what it asks for read once and then projected.
    assert gateway.tasks == ["rolemap.extract", "rolemap.fit"]
    assert gateway.templates[0] == "role_extraction@v2"
    assert "- Own the ledger" in gateway.shown[0]["postings"]
    # A role filled in keeps the title the user gave it.
    assert uow.store.postings[posting_id].title == "Staff Engineer"
    assert [r.statement for r in uow.store.requirements.values()] == ["skill 0.9", "skill 0.4"]
    [source] = uow.store.requirement_fits.values()
    assert source.target_profile == {"backend": 80}
    assert source.requirement_map == {"skill 0.9": "backend", "skill 0.4": None}
    [fit] = uow.store.fits.values()
    assert fit.source_fit_id == source.id and fit.assessment_id == assessment_id
    assert [(g["dimension_key"], g["delta"]) for g in fit.gaps] == [("backend", -20)]
    assert [u["statement"] for u in fit.uncovered] == ["skill 0.4"]
    [listed] = await target.own_postings(OWNER)
    assert (listed.status, listed.fit, listed.is_stale) == ("ready", fit.score, False)


async def test_a_posting_fit_is_never_an_ai_call() -> None:
    """Worked out from the AI fit with a gateway that refuses every call."""

    class NoCalls:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a posting fit made an AI call")

    target, rolemap, uow, rolemap_uow = _services(OwnPostingGateway(target=80))
    await _with_strengths(rolemap)
    await _scored(target)
    [source] = uow.store.requirement_fits.values()

    local_rolemap = RoleMapService(
        rolemap_uow,
        market=FakeMarket(),  # type: ignore[arg-type]
        gateway=NoCalls(),  # type: ignore[arg-type]
        embedding_model="test-model",
        top_k=10,
        candidate_count=20,
    )
    local = _target(uow, local_rolemap)
    strengths = await local_rolemap.strengths(OWNER)
    assert strengths is not None
    await local._create_fit(OWNER, strengths, source)

    fits = sorted(uow.store.fits.values(), key=lambda f: str(f.created_at))
    assert len(fits) == 2 and fits[0].score == fits[1].score
    assert all(f.source_fit_id == source.id for f in fits)


async def test_a_failed_read_is_recorded_on_the_run_not_raised() -> None:
    target, rolemap, uow, _ = _services(OwnPostingGateway(fails="rolemap.fit"))
    await _with_strengths(rolemap)
    posting_id = await _scored(target)

    [listed] = await target.own_postings(OWNER)
    assert listed.status == "failed" and listed.error_code == "ai_budget_exceeded"
    assert listed.fit is None and uow.store.fits == {}
    with pytest.raises(Exception, match="not been scored"):
        await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))


async def test_setting_a_stale_one_as_the_target_keeps_its_requirements_and_spends_one_call() -> (
    None
):
    gateway = OwnPostingGateway(target=80)
    target, rolemap, _uow, _ = _services(gateway)
    await _with_strengths(rolemap, backend=60)
    posting_id = await _scored(target)
    # A new analysis: the fit was scored against earlier strengths.
    await _with_strengths(rolemap, backend=80)
    [stale] = await target.own_postings(OWNER)
    assert stale.is_stale
    gateway.tasks.clear()

    await target.evaluate_own_posting(OWNER, await _target_run(target, posting_id))

    assert gateway.tasks == ["rolemap.fit"]
    snapshot = await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))
    assert [(d.dimension_key, d.user_score) for d in snapshot.dimensions] == [("backend", 80)]
    [fresh] = await target.own_postings(OWNER)
    assert not fresh.is_stale


async def test_setting_one_with_a_current_fit_as_the_target_queues_nothing_and_costs_nothing() -> (
    None
):
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway)
    await _with_strengths(rolemap)
    posting_id = await _scored(target)
    runs = len(uow.store.evaluations)

    posting, run_id = await target.set_as_target(OWNER, posting_id)

    assert run_id is None and posting.status == "ready"
    assert len(uow.store.evaluations) == runs
    priced = await target.estimate_target(OWNER, posting_id)
    assert priced["cost_usd"] == "0"


async def test_setting_one_as_the_target_while_it_runs_joins_the_run() -> None:
    target, rolemap, _uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id = await _add_own(target)
    await _target_run(target, posting_id)

    posting, run_id = await target.set_as_target(OWNER, posting_id)

    assert run_id is None and posting.status == "running"


async def test_setting_one_as_the_target_is_priced_at_reading_and_scoring_it() -> None:
    gateway = OwnPostingGateway()
    target, _rolemap, _uow, _ = _services(gateway)
    posting_id = await _add_own(target)

    priced = await target.estimate_target(OWNER, posting_id)

    assert priced == {"cost_usd": "0.20", "model_id": "claude-opus-5", "rate_is_published": True}
    assert gateway.templates[0] == "estimate:fit_projection@v1"
    assert "estimate:role_extraction@v2" in gateway.templates


async def test_a_role_with_nothing_listed_is_priced_at_estimating_what_it_asks() -> None:
    gateway = OwnPostingGateway()
    target, _rolemap, _uow, _ = _services(gateway)
    posting = await target.add_own_posting(
        OWNER, title="Platform Lead", company_name=None, requirements=()
    )

    priced = await target.estimate_target(OWNER, posting.private_job_posting_id)

    assert priced["cost_usd"] == "0.20"
    assert "estimate:typical_requirements@v1" in gateway.templates


async def test_a_role_with_nothing_listed_has_what_it_asks_estimated_from_its_title() -> None:
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway)
    await _with_strengths(rolemap)
    posting = await target.add_own_posting(
        OWNER, title="Platform Lead", company_name=None, requirements=()
    )

    await target.evaluate_own_posting(
        OWNER, await _target_run(target, posting.private_job_posting_id)
    )

    assert gateway.templates[:2] == ["typical_requirements@v1", "fit_projection@v1"]
    assert "Platform Lead" in gateway.shown[0]["job"]
    assert [r.statement for r in uow.store.requirements.values()] == ["skill 0.9", "skill 0.4"]
    [listed] = await target.own_postings(OWNER)
    assert listed.status == "ready" and listed.has_estimated_requirements


async def test_a_snapshot_of_a_posting_of_your_own_is_planned_against_its_jd() -> None:
    target, rolemap, _uow, _ = _services(OwnPostingGateway(target=80))
    await _with_strengths(rolemap)
    posting_id = await _scored(target)

    snapshot = await target.snapshot(OWNER, TargetRef(private_job_posting_id=str(posting_id)))

    assert (snapshot.title, snapshot.company, snapshot.role_id) == (
        "Staff Engineer",
        "Northwind",
        None,
    )
    assert snapshot.basis is RequirementBasis.POSTING
    assert [r.statement for r in snapshot.requirements] == ["skill 0.9", "skill 0.4"]
    assert [u.statement for u in snapshot.uncovered] == ["skill 0.4"]


async def test_removing_a_posting_of_your_own_deletes_it_and_its_fit() -> None:
    target, rolemap, uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id = await _scored(target)

    await target.remove_own_posting(OWNER, posting_id)

    assert await target.own_postings(OWNER) == []
    assert not (
        uow.store.postings
        or uow.store.evaluations
        or uow.store.requirements
        or uow.store.requirement_fits
        or uow.store.fits
    )
    with pytest.raises(NotFoundError):
        await target.remove_own_posting(OWNER, posting_id)


async def test_another_users_posting_is_not_found() -> None:
    target, rolemap, _uow, _ = _services()
    await _with_strengths(rolemap)
    posting_id = await _add_own(target)

    assert await target.own_postings(OTHER) == []
    with pytest.raises(NotFoundError):
        await target.own_posting(OTHER, posting_id)
    with pytest.raises(NotFoundError):
        await target.snapshot(OTHER, TargetRef(private_job_posting_id=str(posting_id)))


# --- uploaded as a file (ADR 0033) -------------------------------------------

_JD_FILE = b"Own the ledger. Lead incident response."


async def _upload(
    target: TargetService,
    content: bytes = _JD_FILE,
    *,
    content_type: str = "text/plain",
    title: str | None = " Staff Engineer ",
) -> uuid.UUID:
    posting = await target.upload_own_posting(
        OWNER,
        title=title,
        company_name=None,
        filename="staff-engineer.txt",
        content_type=content_type,
        content=content,
    )
    return posting.private_job_posting_id


async def test_an_uploaded_posting_is_stored_as_a_file_and_spends_nothing() -> None:
    store = FakeObjectStore()
    gateway = OwnPostingGateway()
    target, _rolemap, uow, _ = _services(gateway, store)

    posting_id = await _upload(target)

    [listed] = await target.own_postings(OWNER)
    assert (listed.title, listed.source, listed.filename, listed.status) == (
        "Staff Engineer",
        "uploaded",
        "staff-engineer.txt",
        None,
    )
    stored = uow.store.postings[posting_id]
    assert stored.job_description is None and stored.storage_key is not None
    # Nothing reads the file in the request: it is only stored.
    assert store.objects == {stored.storage_key: _JD_FILE}
    assert uow.store.evaluations == {} and gateway.tasks == []


async def test_scoring_an_uploaded_posting_reads_its_file_first_and_then_drops_it() -> None:
    store = FakeObjectStore()
    gateway = OwnPostingGateway(target=80)
    target, rolemap, uow, _ = _services(gateway, store)
    await _with_strengths(rolemap)
    posting_id = await _upload(target)

    await target.evaluate_own_posting(OWNER, await _target_run(target, posting_id))

    assert gateway.tasks == ["rolemap.extract", "rolemap.fit"]
    assert "Own the ledger" in gateway.shown[0]["postings"]
    stored = uow.store.postings[posting_id]
    assert stored.job_description == _JD_FILE.decode()
    assert stored.storage_key is None and store.objects == {}
    # It had a title of the user's own, so it keeps it.
    assert stored.title == "Staff Engineer"
    [listed] = await target.own_postings(OWNER)
    assert listed.status == "ready" and listed.fit is not None


async def test_an_upload_without_a_title_is_named_after_its_file_then_its_job() -> None:
    target, rolemap, uow, _ = _services(OwnPostingGateway(target=80))
    await _with_strengths(rolemap)

    posting_id = await _upload(target, title=None)
    assert uow.store.postings[posting_id].title == "staff-engineer"

    await target.evaluate_own_posting(OWNER, await _target_run(target, posting_id))

    stored = uow.store.postings[posting_id]
    assert stored.title == "Principal Engineer" and not stored.has_placeholder_title


def _blank_pdf() -> bytes:
    """A PDF with a page and no text on it."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(b"not a pdf at all", "application/pdf"), (_blank_pdf(), "application/pdf")],
)
async def test_a_file_that_cannot_be_read_fails_the_run_and_spends_nothing(
    content: bytes, content_type: str
) -> None:
    store = FakeObjectStore()
    gateway = OwnPostingGateway()
    target, rolemap, uow, _ = _services(gateway, store)
    await _with_strengths(rolemap)
    posting_id = await _upload(target, content, content_type=content_type)

    await target.evaluate_own_posting(OWNER, await _target_run(target, posting_id))

    assert gateway.tasks == []
    [listed] = await target.own_postings(OWNER)
    assert listed.status == "failed" and listed.error_code == "validation_failed"
    # The file stays until the posting is removed, and goes with it.
    assert len(store.objects) == 1
    await target.remove_own_posting(OWNER, posting_id)
    assert store.objects == {} and uow.store.postings == {}


@pytest.mark.parametrize(
    ("content", "content_type", "message"),
    [
        (b"x" * 1_001, "text/plain", "larger than we accept"),
        (b"\x89PNG", "image/png", "not a format we can read"),
        (b"", "text/plain", "empty"),
    ],
)
async def test_an_upload_that_cannot_be_a_jd_is_refused_before_anything_is_stored(
    content: bytes, content_type: str, message: str
) -> None:
    store = FakeObjectStore()
    target, _rolemap, uow, _ = _services(store=store)

    with pytest.raises(ValidationError, match=message):
        await _upload(target, content, content_type=content_type)
    assert store.objects == {} and uow.store.postings == {}


async def test_an_unread_upload_is_priced_as_a_ceiling() -> None:
    gateway = OwnPostingGateway()
    target, _rolemap, _uow, _ = _services(gateway)
    posting_id = await _upload(target)

    priced = await target.estimate_target(OWNER, posting_id)

    assert priced == {"cost_usd": "0.20", "model_id": "claude-opus-5", "rate_is_published": True}
