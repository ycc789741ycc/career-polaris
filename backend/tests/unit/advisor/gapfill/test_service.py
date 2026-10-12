"""Fill the gap's use cases against in-memory storage: writing questions for a
Target's gaps, and the one submit that turns answers into evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from advisor.gapfill import Answer, GapFillService
from advisor.gapfill.domain import GapAnswersSubmitted, QuestionSetStatus
from advisor.profile import AnswerRecord, EvidenceSource
from advisor.profile.domain import EvidenceGranularity
from advisor.target import DimensionGap, TargetRef, TargetSnapshot, UncoveredGap
from advisor.target.domain import Requirement, RequirementBasis
from kernel.errors import (
    BudgetExceededError,
    ConflictError,
    TargetUnusableError,
    ValidationError,
)
from kernel.progress import Progress
from tests.unit.advisor.gapfill.fakes import FakeGapFillUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
REF = TargetRef("00000000-0000-0000-0000-0000000000aa")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _snapshot(*, cleared: bool = False) -> TargetSnapshot:
    user = 90 if cleared else 60
    return TargetSnapshot(
        ref=REF,
        title="Staff Backend Engineer",
        company="Northwind Pay",
        role_id=REF.role_id,
        role_name="Staff Backend Engineer",
        requirements=(Requirement("Own incidents", 1.0, "advanced"),),
        basis=RequirementBasis.ROLE,
        fit_score=70,
        dimensions=(DimensionGap("incidents", "Incident response", user, 80, lift=9),),
        uncovered=() if cleared else (UncoveredGap("Multi-region capacity", 0.5, lift=4),),
        requirement_map={"Own incidents": "incidents"},
        taken_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


class FakeTarget:
    """A Target already scored, unless ``scored`` is false: then it is an
    opening whose fit ``create_opening_fit`` works out (ADR 0073)."""

    def __init__(self, snapshot: TargetSnapshot, *, scored: bool = True) -> None:
        self.current = snapshot
        self.scored = scored
        self.scorings = 0
        self.readings: list[Any] = []

    async def snapshot(
        self, owner_id: uuid.UUID, ref: TargetRef, *, with_answers: bool = True
    ) -> TargetSnapshot:
        if not self.scored:
            raise TargetUnusableError("run its gap analysis in Fill the gap first")
        return self.current

    async def is_scored(self, owner_id: uuid.UUID, ref: TargetRef) -> bool:
        return self.scored

    async def get_label(self, owner_id: uuid.UUID, ref: TargetRef) -> str:
        return "Staff Backend Engineer · Northwind Pay"

    async def estimate_opening_fit(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        return {"cost_usd": "0.20", "model_id": "claude-opus-5", "rate_is_published": True}

    async def create_opening_fit(
        self, owner_id: uuid.UUID, ref: TargetRef, *, checkpoint: Any
    ) -> None:
        await checkpoint()
        self.scorings += 1
        self.scored = True

    async def record_answer_readings(
        self, owner_id: uuid.UUID, ref: TargetRef, **kwargs: Any
    ) -> int:
        self.readings.append(kwargs)
        return len(kwargs["readings"])


@dataclass(frozen=True)
class _Evidence:
    id: uuid.UUID
    source: EvidenceSource
    reference: str
    fact: str
    observed_on: date | None = None
    granularity: EvidenceGranularity = EvidenceGranularity.ITEM
    stated_on: date | None = None


@dataclass
class FakeProfile:
    recorded: list[list[AnswerRecord]] = field(default_factory=list)
    # Evidence ids the profile still holds; None means every one recorded.
    kept: set[str] | None = None
    stored: list[str] = field(default_factory=list)
    answers: list[Any] = field(default_factory=list)

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        return set(self.stored) if self.kept is None else self.kept

    async def snapshot(self, owner_id: uuid.UUID) -> Any:
        return type(
            "Snapshot",
            (),
            {
                "evidence": (
                    _Evidence(uuid.uuid4(), EvidenceSource.GITHUB, "api", "Wrote the RFC"),
                    *self.answers,
                )
            },
        )()

    async def record_answers(self, owner_id: uuid.UUID, answers: list[AnswerRecord]) -> Any:
        self.recorded.append(list(answers))
        stored = [
            _Evidence(uuid.uuid4(), EvidenceSource.USER_ANSWER, "Your answer", a.fact)
            for a in answers
        ]
        self.stored += [str(e.id) for e in stored]
        self.answers += stored
        return stored


@dataclass
class _Result:
    value: Any
    model_id: str = "claude-opus-5"
    template_version: str = "gap_questions@v1"


class FakeGateway:
    def __init__(self, reply: dict[str, Any] | None = None, error: Exception | None = None):
        self.reply = reply or _reply()
        self.error = error
        self.inputs: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, inputs: dict[str, str], **kwargs: Any) -> _Result:
        # As the real gateway does with a callback: report before the call,
        # then part way through the reply (ADR 0042).
        report = kwargs.get("on_progress")
        if report is not None:
            await report(Progress(fraction=0.0, estimated_cost_usd=Decimal("0.02")))
        self.inputs.append(inputs)
        if report is not None:
            await report(Progress(fraction=0.5, estimated_cost_usd=Decimal("0.02")))
        if self.error is not None:
            raise self.error
        return _Result(value=kwargs["output_schema"].model_validate(self.reply))


def _reply(**extra: Any) -> dict[str, Any]:
    return {
        "questions": [
            {
                "gap_key": "req:multi-region-capacity",
                "text": "Have you planned capacity across regions?",
                "asked_because": "Nothing in your sources speaks to it.",
                "answer_type": "choice",
                "choices": ["Yes", "Partly", "No"],
            },
            {
                "gap_key": "dim:incidents",
                "text": "Have you led an incident response?",
                "asked_because": "It rests on one post-incident review.",
                "answer_type": "both",
                "choices": ["Yes", "Not yet"],
            },
        ],
        **extra,
    }


def _service(
    uow: FakeGapFillUnitOfWork,
    *,
    target: FakeTarget | None = None,
    profile: FakeProfile | None = None,
    gateway: FakeGateway | None = None,
) -> GapFillService:
    return GapFillService(
        uow,
        target=target or FakeTarget(_snapshot()),  # type: ignore[arg-type]
        profile=profile or FakeProfile(),  # type: ignore[arg-type]
        gateway=gateway or FakeGateway(),  # type: ignore[arg-type]
    )


async def _written(service: GapFillService) -> Any:
    requested = await service.request(OWNER, REF)
    await service.write(OWNER, requested.id)
    return await service.get(OWNER, requested.id)


async def test_questions_are_asked_about_the_targets_costliest_gaps_first() -> None:
    uow = FakeGapFillUnitOfWork()
    gateway = FakeGateway()
    service = _service(uow, gateway=gateway)

    requested = await service.request(OWNER, REF)
    assert requested.status == "writing" and requested.questions == ()
    assert [(g.key, g.status, g.lift) for g in requested.gaps] == [
        ("dim:incidents", "partial", 9),
        ("req:multi-region-capacity", "no_evidence", 4),
    ]

    await service.write(OWNER, requested.id)
    written = await service.get(OWNER, requested.id)

    assert written.status == "ready" and written.model_id == "claude-opus-5"
    # Ordered by the gap's worth, not by how the model listed them.
    assert [q.gap_key for q in written.questions] == [
        "dim:incidents",
        "req:multi-region-capacity",
    ]
    assert "worth up to 9 fit points" in gateway.inputs[0]["gaps"]
    assert "- (github, undated) api: Wrote the RFC" in gateway.inputs[0]["evidence"]
    assert (await service.current(OWNER, REF)) == written


async def test_a_target_with_nothing_to_ask_is_refused_up_front() -> None:
    service = _service(FakeGapFillUnitOfWork(), target=FakeTarget(_snapshot(cleared=True)))

    with pytest.raises(TargetUnusableError, match="nothing to ask"):
        await service.request(OWNER, REF)


async def test_a_new_set_supersedes_the_targets_earlier_one_once_written() -> None:
    uow = FakeGapFillUnitOfWork()
    service = _service(uow)
    first = await _written(service)

    second = await _written(service)

    # Superseded only once the new set is written, so cancelling it would
    # have left the first current (ADR 0042).
    assert uow.store.sets[first.id].status is QuestionSetStatus.SUPERSEDED
    current = await service.current(OWNER, REF)
    assert current is not None and current.id == second.id


async def test_questions_about_an_unasked_gap_fail_the_set_not_the_job() -> None:
    reply = _reply()
    reply["questions"][0]["gap_key"] = "dim:invented"
    service = _service(FakeGapFillUnitOfWork(), gateway=FakeGateway(reply))

    written = await _written(service)

    assert (written.status, written.error_code) == ("failed", "validation_failed")


async def test_a_budget_failure_is_recorded_on_the_set() -> None:
    service = _service(
        FakeGapFillUnitOfWork(), gateway=FakeGateway(error=BudgetExceededError("spent"))
    )

    written = await _written(service)

    assert (written.status, written.error_code) == ("failed", "ai_budget_exceeded")


async def test_submitting_records_every_answer_as_evidence_at_once() -> None:
    uow = FakeGapFillUnitOfWork()
    profile = FakeProfile()
    service = _service(uow, profile=profile)
    written = await _written(service)
    lead, region = written.questions

    done = await service.submit(
        OWNER,
        written.id,
        [
            Answer(question_id=lead.id, choice="Yes", text="Led the Feb outage bridge."),
            Answer(question_id=region.id),
        ],
    )

    assert (len(done.evidence_ids), done.skipped) == (1, 1)
    [[record]] = profile.recorded
    assert record.fact == ("Have you led an incident response? Yes — Led the Feb outage bridge.")
    after = await service.get(OWNER, written.id)
    assert after.submitted_at is not None
    assert after.questions[0].evidence_id == done.evidence_ids[0]
    assert after.questions[1].evidence_id is None
    assert uow.store.events == [
        GapAnswersSubmitted(
            owner_id=OWNER,
            set_id=written.id,
            role_id=uuid.UUID(REF.role_id),
            job_posting_id=None,
            evidence_ids=(str(done.evidence_ids[0]),),
        )
    ]


async def test_a_batch_with_one_bad_answer_stores_nothing() -> None:
    profile = FakeProfile()
    service = _service(FakeGapFillUnitOfWork(), profile=profile)
    written = await _written(service)
    lead, region = written.questions

    with pytest.raises(ValidationError):
        await service.submit(
            OWNER,
            written.id,
            [
                Answer(question_id=lead.id, choice="Yes"),
                Answer(question_id=region.id, choice="Not an option"),
            ],
        )

    assert profile.recorded == []


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [Answer(question_id=uuid.uuid4(), choice="Yes")],
    ],
)
async def test_a_submit_with_nothing_to_record_is_refused(answers: list[Answer]) -> None:
    service = _service(FakeGapFillUnitOfWork())
    written = await _written(service)

    with pytest.raises(ValidationError):
        await service.submit(OWNER, written.id, answers)


async def test_a_set_is_submitted_once() -> None:
    service = _service(FakeGapFillUnitOfWork())
    written = await _written(service)
    answers = [Answer(question_id=written.questions[0].id, choice="Yes")]
    await service.submit(OWNER, written.id, answers)

    with pytest.raises(ValidationError, match="already submitted"):
        await service.submit(OWNER, written.id, answers)


# --- answers a gap plan may cite (ADR 0036) ----------------------------------


async def test_a_targets_answers_are_listed_by_gap_newest_first() -> None:
    uow = FakeGapFillUnitOfWork()
    service = _service(uow)
    first = await _written(service)
    lead = first.questions[0]
    earlier = await service.submit(OWNER, first.id, [Answer(question_id=lead.id, choice="Yes")])
    second = await _written(service)
    later = await service.submit(
        OWNER, second.id, [Answer(question_id=second.questions[1].id, choice="Partly")]
    )

    answers = await service.get_answers(OWNER, REF)

    assert [(a.gap_key, a.evidence_id) for a in answers] == [
        ("req:multi-region-capacity", later.evidence_ids[0]),
        ("dim:incidents", earlier.evidence_ids[0]),
    ]
    elsewhere = TargetRef("00000000-0000-0000-0000-0000000000bb")
    assert await service.get_answers(OWNER, elsewhere) == ()


async def test_an_answer_whose_evidence_is_gone_is_left_out() -> None:
    profile = FakeProfile(kept=set())
    service = _service(FakeGapFillUnitOfWork(), profile=profile)
    written = await _written(service)
    answer = Answer(question_id=written.questions[0].id, choice="Yes")
    await service.submit(OWNER, written.id, [answer])

    assert await service.get_answers(OWNER, REF) == ()


async def test_unanswered_questions_are_not_answers() -> None:
    service = _service(FakeGapFillUnitOfWork())
    await _written(service)

    assert await service.get_answers(OWNER, REF) == ()


# -- a job in the background (ADR 0042) -------------------------------------------


class RecordingSets:
    """Every stage and progress the set passes, as each write stores it."""

    def __init__(self, uow: FakeGapFillUnitOfWork) -> None:
        self.seen: list[tuple[str | None, float]] = []
        original = uow.store.sets.__class__.__setitem__
        store = uow.store.sets
        seen = self.seen

        class Watching(dict):  # type: ignore[type-arg]
            def __setitem__(self, key: Any, value: Any) -> None:
                seen.append((str(value.stage) if value.stage else None, value.progress))
                original(self, key, value)

        uow.store.sets = Watching(store)


async def test_writing_passes_its_stages_in_order_and_never_goes_back() -> None:
    uow = FakeGapFillUnitOfWork()
    watching = RecordingSets(uow)
    service = _service(uow)

    written = await _written(service)

    assert written.status == "ready"
    stages = [stage for stage, _ in watching.seen if stage is not None]
    assert stages[0] == "reading" and stages[-1] == "checking"
    assert stages.index("writing") < stages.index("checking")
    progress = [value for _, value in watching.seen]
    assert progress == sorted(progress)
    assert uow.store.sets[written.id].estimated_cost_usd == Decimal("0.02")


async def test_a_set_cancelled_before_its_call_makes_none() -> None:
    uow = FakeGapFillUnitOfWork()
    gateway = FakeGateway()
    service = _service(uow, gateway=gateway)
    requested = await service.request(OWNER, REF)

    await service.cancel(OWNER, requested.id)
    await service.write(OWNER, requested.id)

    assert gateway.inputs == []
    assert uow.store.sets[requested.id].status is QuestionSetStatus.CANCELLED
    assert await service.current(OWNER, REF) is None


async def test_a_set_cancelled_while_written_saves_nothing_and_the_earlier_stays() -> None:
    uow = FakeGapFillUnitOfWork()
    service = _service(uow)
    first = await _written(service)
    second = await service.request(OWNER, REF)

    class CancelMidway(FakeGateway):
        async def run(self, owner_id: uuid.UUID, **kwargs: Any) -> _Result:
            await service.cancel(OWNER, second.id)
            return await super().run(owner_id, **kwargs)

    service._gateway = CancelMidway()  # type: ignore[assignment]
    await service.write(OWNER, second.id)

    assert uow.store.sets[second.id].status is QuestionSetStatus.CANCELLED
    assert [q for q in uow.store.questions.values() if q.set_id == second.id] == []
    current = await service.current(OWNER, REF)
    assert current is not None and current.id == first.id


async def test_only_a_set_being_written_can_be_cancelled_and_one_at_a_time() -> None:
    service = _service(FakeGapFillUnitOfWork())
    written = await _written(service)
    with pytest.raises(ConflictError):
        await service.cancel(OWNER, written.id)

    await service.request(OWNER, REF)
    with pytest.raises(ConflictError):
        await service.request(OWNER, REF)


async def test_a_set_being_written_is_listed_as_a_running_job() -> None:
    service = _service(FakeGapFillUnitOfWork())
    requested = await service.request(OWNER, REF)

    [job] = await service.running_jobs(OWNER)

    assert (job.kind, job.id, job.role_id) == ("questions", str(requested.id), REF.role_id)
    assert await service.running_jobs(OTHER) == ()


OPENING = TargetRef("00000000-0000-0000-0000-0000000000aa", "00000000-0000-0000-0000-0000000000bb")


async def test_an_unscored_opening_is_scored_first_then_asked_about() -> None:
    """Its gaps are known only once it is scored, so the set is recorded
    without them and the job scores it before it writes (ADR 0073)."""
    uow = FakeGapFillUnitOfWork()
    target = FakeTarget(_snapshot(), scored=False)
    service = _service(uow, target=target)

    requested = await service.request(OWNER, OPENING)
    assert requested.status == "writing" and requested.gaps == ()
    assert requested.label == "Staff Backend Engineer · Northwind Pay"

    await service.write(OWNER, requested.id)
    written = await service.get(OWNER, requested.id)

    assert target.scorings == 1
    assert written.status == "ready"
    assert [g.key for g in written.gaps] == ["dim:incidents", "req:multi-region-capacity"]


async def test_a_scored_opening_with_nothing_to_ask_fails_its_set() -> None:
    uow = FakeGapFillUnitOfWork()
    service = _service(uow, target=FakeTarget(_snapshot(cleared=True), scored=False))

    requested = await service.request(OWNER, OPENING)
    await service.write(OWNER, requested.id)
    found = await service.get(OWNER, requested.id)

    assert found.status == "failed" and found.error_code == "target_unusable"
    assert found.error_message is not None and "nothing to ask" in found.error_message


async def test_a_set_cancelled_while_its_opening_is_scored_writes_nothing() -> None:
    uow = FakeGapFillUnitOfWork()
    gateway = FakeGateway()
    target = FakeTarget(_snapshot(), scored=False)
    service = _service(uow, target=target, gateway=gateway)
    requested = await service.request(OWNER, OPENING)
    await service.cancel(OWNER, requested.id)

    await service.write(OWNER, requested.id)

    assert target.scorings == 0 and gateway.inputs == []


async def test_an_unscored_opening_is_priced_with_its_scoring() -> None:
    class PricedGateway(FakeGateway):
        async def estimate(self, owner_id: uuid.UUID, **_: Any) -> Any:
            return type(
                "Estimate",
                (),
                {
                    "cost_usd": Decimal("0.05"),
                    "model_id": "claude-opus-5",
                    "input_tokens": 900,
                    "rate_is_published": True,
                },
            )()

    service = _service(
        FakeGapFillUnitOfWork(),
        target=FakeTarget(_snapshot(), scored=False),
        gateway=PricedGateway(),
    )

    priced = await service.estimate_cost(OWNER, OPENING)

    assert priced["cost_usd"] == "0.25"
    assert priced["rate_is_published"] is True


# --- reading the answers into the fit (ADR 0077) -----------------------------


def _readings(*extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "readings": [
            {
                "gap_key": "dim:incidents",
                "score": 75,
                "coverage": None,
                "reasoning": "Led the February outage bridge.",
                "evidence_ids": ["E1"],
            },
            *extra,
        ]
    }


async def _submitted(service: GapFillService) -> Any:
    written = await _written(service)
    lead, _region = written.questions
    await service.submit(
        OWNER, written.id, [Answer(question_id=lead.id, choice="Yes", text="Led it.")]
    )
    return written


async def test_submitted_answers_are_read_into_the_targets_fit() -> None:
    uow = FakeGapFillUnitOfWork()
    target = FakeTarget(_snapshot())
    gateway = FakeGateway()
    service = _service(uow, target=target, gateway=gateway)
    written = await _submitted(service)
    gateway.reply = _readings()

    started = await service.start_fit_reading(OWNER, written.id)
    assert started.fit_reading == "reading"
    [job] = await service.running_jobs(OWNER)
    assert (job.kind, job.stage) == ("fit_update", "reading_answers")
    await service.read_answers(OWNER, written.id)

    [recorded] = target.readings
    [reading] = recorded["readings"]
    assert (reading.gap_key, reading.score, reading.coverage) == ("dim:incidents", 75, None)
    assert recorded["question_set_id"] == written.id
    # The gap as the analysis scored it, and the answer given about it, dated.
    sent = gateway.inputs[-1]["gaps"]
    assert "the analysis scored 60, the job expects 80" in sent
    assert "[E1] (user_answer, undated) Your answer: Have you led an incident response?" in sent
    assert (await service.get(OWNER, written.id)).fit_reading == "ready"
    assert await service.running_jobs(OWNER) == ()


async def test_a_reading_citing_another_gaps_answer_is_dropped_not_the_rest() -> None:
    target = FakeTarget(_snapshot())
    gateway = FakeGateway()
    service = _service(FakeGapFillUnitOfWork(), target=target, gateway=gateway)
    written = await _submitted(service)
    gateway.reply = _readings(
        {
            "gap_key": "req:multi-region-capacity",
            "score": None,
            "coverage": "covered",
            "reasoning": "Unanswered, so it borrows another answer.",
            "evidence_ids": ["E1"],
        },
        {
            "gap_key": "dim:incidents",
            "score": 99,
            "coverage": None,
            "reasoning": "A second reading of the same gap.",
            "evidence_ids": ["E7"],
        },
    )

    await service.start_fit_reading(OWNER, written.id)
    await service.read_answers(OWNER, written.id)

    [recorded] = target.readings
    assert [(r.gap_key, r.score) for r in recorded["readings"]] == [("dim:incidents", 75)]


async def test_answers_are_read_only_once_submitted_and_one_reading_at_a_time() -> None:
    service = _service(FakeGapFillUnitOfWork())
    written = await _written(service)
    with pytest.raises(ConflictError, match="once they are submitted"):
        await service.start_fit_reading(OWNER, written.id)

    lead, _ = written.questions
    await service.submit(OWNER, written.id, [Answer(question_id=lead.id, choice="Yes")])
    await service.start_fit_reading(OWNER, written.id)
    with pytest.raises(ConflictError, match="already being read"):
        await service.start_fit_reading(OWNER, written.id)


async def test_a_reading_cancelled_keeps_the_answers_and_records_nothing() -> None:
    target = FakeTarget(_snapshot())
    gateway = FakeGateway()
    service = _service(FakeGapFillUnitOfWork(), target=target, gateway=gateway)
    written = await _submitted(service)
    gateway.reply = _readings()
    await service.start_fit_reading(OWNER, written.id)

    await service.cancel(OWNER, written.id)
    await service.read_answers(OWNER, written.id)

    after = await service.get(OWNER, written.id)
    assert (after.fit_reading, after.submitted_at is not None) == ("cancelled", True)
    assert target.readings == []
    # And it can be read again on request.
    assert (await service.start_fit_reading(OWNER, written.id)).fit_reading == "reading"


async def test_a_failed_reading_is_recorded_on_the_set() -> None:
    gateway = FakeGateway()
    service = _service(FakeGapFillUnitOfWork(), gateway=gateway)
    written = await _submitted(service)
    gateway.error = BudgetExceededError("spent")

    await service.start_fit_reading(OWNER, written.id)
    await service.read_answers(OWNER, written.id)

    after = await service.get(OWNER, written.id)
    assert (after.fit_reading, after.fit_reading_error_code) == ("failed", "ai_budget_exceeded")


async def test_reading_the_answers_is_priced_as_a_ceiling_before_they_are_submitted() -> None:
    class Estimating(FakeGateway):
        async def estimate(self, owner_id: uuid.UUID, **kwargs: Any) -> Any:
            self.inputs.append(kwargs["inputs"])
            return type(
                "Estimate",
                (),
                {
                    "cost_usd": Decimal("0.03"),
                    "model_id": "claude-opus-5",
                    "input_tokens": 900,
                    "rate_is_published": True,
                },
            )()

    gateway = Estimating()
    service = _service(FakeGapFillUnitOfWork(), gateway=gateway)
    written = await _written(service)

    estimate = await service.estimate_fit_reading(OWNER, written.id)

    assert estimate["cost_usd"] == "0.03"
    # Every question, answered at full length.
    assert gateway.inputs[-1]["gaps"].count("x" * 2000) == 2
