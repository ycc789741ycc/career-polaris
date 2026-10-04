"""Profile use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from advisor.profile import (
    AnswerRecord,
    EvidenceSource,
    PositionReading,
    ProfileService,
    get_evidence_line,
)
from advisor.profile.domain import (
    CareerPosition,
    CareerPositionFilter,
    ConnectionStatus,
    EvidenceGranularity,
    ProfileUpdated,
    ResumeStatus,
    SourceSynced,
)
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from kernel.crypto import decrypt
from kernel.errors import NotFoundError, UpstreamFailedError, ValidationError
from tests.unit.advisor.profile.fakes import FakeObjectStore, FakeProfileUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")

pytestmark = pytest.mark.usefixtures("clean_env")


class FakeConnector(Connector):
    kind = "github"

    def __init__(
        self,
        drafts: list[EvidenceDraft] | None = None,
        *,
        fails: bool = False,
        account: str | None = "octo",
        retired_refs: tuple[str, ...] = (),
        replaced_refs: tuple[str, ...] = (),
    ) -> None:
        self.drafts = drafts or []
        self.retired_refs = retired_refs
        self.replaced_refs = replaced_refs
        self.fails = fails
        self.account = account
        self.tokens: list[str] = []

    async def account_name(self, client: Any, token: str) -> str:
        if self.account is None:
            raise UpstreamFailedError("GitHub did not return an account")
        return self.account

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        self.tokens.append(token)
        if self.fails:
            raise UpstreamFailedError("GitHub said no")
        return self.drafts


def _draft(ref: str, fact: str = "Shipped the thing") -> EvidenceDraft:
    return EvidenceDraft(
        external_ref=ref,
        reference=f"https://github.test/{ref}",
        fact=fact,
        observed_on=date(2026, 9, 1),
    )


def _service(
    uow: FakeProfileUnitOfWork, *, connector: FakeConnector | None = None
) -> ProfileService:
    return ProfileService(
        uow,
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
        connectors={"github": connector or FakeConnector()},
        resume_max_bytes=10_000,
        resume_max_pages=5,
        http_timeout_seconds=1,
        user_agent="test",
    )


# --- connections -----------------------------------------------------------


async def test_a_connection_stores_its_tokens_encrypted_and_reconnects_in_place() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    await profile.store_connection(
        OWNER,
        kind="github",
        access_token="gho_first",
        refresh_token=None,
        scopes=("repo",),
        expires_at=None,
    )
    view = await profile.store_connection(
        OWNER,
        kind="github",
        access_token="gho_second",
        refresh_token="ghr_x",
        scopes=("repo", "read:org"),
        expires_at=None,
    )

    (stored,) = uow.store.connections.values()
    assert "gho_second" not in stored.encrypted_access_token
    assert decrypt(stored.encrypted_access_token, context=str(OWNER)) == "gho_second"
    assert stored.scopes == ("repo", "read:org")
    assert view.account == "octo" and view.status == "connected"


async def test_an_unknown_connector_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).store_connection(
            OWNER, kind="gitlab", access_token="t", refresh_token=None, scopes=(), expires_at=None
        )


async def test_a_sync_turns_a_source_into_evidence_and_bumps_the_version() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("pr/1"), _draft("pr/2")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="gho_x", refresh_token=None, scopes=(), expires_at=None
    )

    assert await profile.sync_connection(OWNER, "github") == 2

    assert connector.tokens == ["gho_x"]
    snapshot = await profile.snapshot(OWNER)
    assert snapshot.version == 1
    assert {e.reference for e in snapshot.evidence} == {
        "https://github.test/pr/1",
        "https://github.test/pr/2",
    }
    assert uow.store.events == [
        ProfileUpdated(owner_id=OWNER, source=EvidenceSource.GITHUB, version=1, count=2),
        SourceSynced(owner_id=OWNER, kind="github", evidence=2),
    ]
    (connection,) = uow.store.connections.values()
    assert connection.last_synced_at is not None


async def test_a_sync_deletes_the_shapes_its_connector_retired_and_keeps_the_rest() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("github:pr:1"), _draft("github:merged:acme/ledger")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")
    await profile.record_answer(OWNER, question_id="q1", question="Led it?", answer="Yes")

    connector.drafts = [_draft("github:commit:abc")]
    connector.retired_refs = ("github:merged:*", "github:pr:*")
    await profile.sync_connection(OWNER, "github")

    snapshot = await profile.snapshot(OWNER)
    assert {(str(e.source), e.reference) for e in snapshot.evidence} == {
        ("github", "https://github.test/github:commit:abc"),
        ("user_answer", "Your answer"),
    }
    assert uow.store.events[-2] == ProfileUpdated(
        owner_id=OWNER, source=EvidenceSource.GITHUB, version=snapshot.version, count=3
    )


async def test_a_retired_pattern_can_match_in_the_middle_of_a_ref() -> None:
    """Jira's old tallies carry the site between the source and the shape."""
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("jira:c1:project:PAY"), _draft("jira:c1:epic:PAY-1")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")

    connector.drafts = []
    connector.retired_refs = ("jira:*:project:*",)
    await profile.sync_connection(OWNER, "github")

    snapshot = await profile.snapshot(OWNER)
    assert [e.reference for e in snapshot.evidence] == ["https://github.test/jira:c1:epic:PAY-1"]


async def test_a_sync_deletes_replaced_facts_it_no_longer_returns() -> None:
    """A Jira ticket reopened since the last sync stops being evidence."""
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector(
        [_draft("jira:issue:1"), _draft("jira:issue:2"), _draft("jira:c1:throughput")],
        replaced_refs=("jira:issue:*",),
    )
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")
    await profile.record_answer(OWNER, question_id="q1", question="Led it?", answer="Yes")

    connector.drafts = [_draft("jira:issue:2")]
    await profile.sync_connection(OWNER, "github")

    snapshot = await profile.snapshot(OWNER)
    assert sorted(e.reference for e in snapshot.evidence) == [
        "Your answer",
        "https://github.test/jira:c1:throughput",
        "https://github.test/jira:issue:2",
    ]
    assert uow.store.events[-2] == ProfileUpdated(
        owner_id=OWNER, source=EvidenceSource.GITHUB, version=snapshot.version, count=2
    )


async def test_a_sync_that_only_retires_facts_still_bumps_the_version() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("github:pr:1")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")

    connector.drafts = []
    connector.retired_refs = ("github:pr:*",)
    assert await profile.sync_connection(OWNER, "github") == 0

    snapshot = await profile.snapshot(OWNER)
    assert snapshot.evidence == () and snapshot.version == 2


async def test_a_resync_restates_facts_rather_than_duplicating_them() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("pr/1")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")

    connector.drafts = [_draft("pr/1", fact="Shipped the thing, twice")]
    await profile.sync_connection(OWNER, "github")

    snapshot = await profile.snapshot(OWNER)
    assert [e.fact for e in snapshot.evidence] == ["Shipped the thing, twice"]
    assert snapshot.version == 2


async def test_a_resync_restates_whether_a_fact_is_one_item_or_a_tally() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("merged/acme")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")
    (before,) = (await profile.snapshot(OWNER)).evidence
    assert before.granularity == EvidenceGranularity.ITEM

    connector.drafts = [
        replace(
            _draft("merged/acme"),
            granularity=EvidenceGranularity.SUMMARY,
            tally=12,
            subject="acme/ledger",
        )
    ]
    await profile.sync_connection(OWNER, "github")

    (after,) = (await profile.snapshot(OWNER)).evidence
    assert (after.granularity, after.tally, after.subject) == (
        EvidenceGranularity.SUMMARY,
        12,
        "acme/ledger",
    )


async def test_a_failed_sync_marks_the_connection_and_writes_nothing() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector(fails=True))
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )

    with pytest.raises(UpstreamFailedError):
        await profile.sync_connection(OWNER, "github")

    (connection,) = uow.store.connections.values()
    assert connection.status is ConnectionStatus.FAILED
    assert connection.last_error == "GitHub said no"
    assert uow.store.evidence == {} and uow.store.events == []


async def test_syncing_a_source_that_is_not_connected_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeProfileUnitOfWork()).sync_connection(OWNER, "github")


async def test_a_token_the_provider_will_not_identify_is_not_stored() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector(account=None))

    with pytest.raises(UpstreamFailedError):
        await profile.store_connection(
            OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
        )

    assert uow.store.connections == {}


async def test_a_sync_refreshes_the_account_name() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("pr/1")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )

    connector.account = "octo-renamed"
    await profile.sync_connection(OWNER, "github")

    (view,) = await profile.connections(OWNER)
    assert view.account == "octo-renamed"


async def test_disconnecting_removes_that_sources_evidence_and_nothing_else() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector([_draft("pr/1"), _draft("pr/2")]))
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")
    uploaded = await profile.upload_resume(
        OWNER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    await profile.parse_resume(OWNER, uploaded.id)
    before = await profile.snapshot(OWNER)
    uow.store.events.clear()

    await profile.disconnect(OWNER, "github")

    after = await profile.snapshot(OWNER)
    assert await profile.connections(OWNER) == []
    assert after.evidence and {e.source for e in after.evidence} == {EvidenceSource.RESUME}
    assert after.version == before.version + 1
    assert uow.store.events == [
        ProfileUpdated(owner_id=OWNER, source=EvidenceSource.GITHUB, version=after.version, count=2)
    ]


async def test_disconnecting_an_unknown_connector_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).disconnect(OWNER, "gitlab")


async def test_disconnecting_twice_is_harmless() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.disconnect(OWNER, "github")
    await profile.disconnect(OWNER, "github")
    assert await profile.connections(OWNER) == []


# --- résumés ---------------------------------------------------------------

RESUME = (
    b"Jane Doe\n"
    b"- Led the migration of the billing platform to event sourcing\n"
    b"- Cut p99 checkout latency from 900ms to 180ms across three regions\n"
)


async def test_an_uploaded_resume_is_parsed_into_evidence_by_the_worker() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    uploaded = await profile.upload_resume(
        OWNER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    assert uploaded.status == "uploaded"
    assert await profile.base_resume_text(OWNER) is None

    written = await profile.parse_resume(OWNER, uploaded.id)

    assert written >= 2
    (stored,) = uow.store.resumes.values()
    assert stored.status is ResumeStatus.PARSED and stored.parsed_at is not None
    text = await profile.base_resume_text(OWNER)
    assert text is not None and "billing platform" in text


@pytest.mark.parametrize(
    ("content_type", "content"),
    [("image/png", b"x"), ("text/plain", b"x" * 20_000)],
)
async def test_a_resume_the_platform_cannot_take_is_refused_before_storing(
    content_type: str, content: bytes
) -> None:
    uow = FakeProfileUnitOfWork()
    with pytest.raises(ValidationError):
        await _service(uow).upload_resume(
            OWNER, filename="cv", content_type=content_type, content=content
        )
    assert uow.store.resumes == {}


async def test_another_users_resume_cannot_be_downloaded() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    theirs = await profile.upload_resume(
        OTHER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    with pytest.raises(NotFoundError):
        await profile.resume_download_url(OWNER, theirs.id)
    assert (await profile.resume_download_url(OTHER, theirs.id)).startswith("https://")


def _service_with_store(uow: FakeProfileUnitOfWork) -> tuple[ProfileService, FakeObjectStore]:
    store = FakeObjectStore()
    profile = ProfileService(
        uow,
        object_store=store,  # type: ignore[arg-type]
        connectors={"github": FakeConnector([_draft("pr/1")])},
        resume_max_bytes=10_000,
        resume_max_pages=5,
        http_timeout_seconds=1,
        user_agent="test",
    )
    return profile, store


async def _upload_and_parse(
    profile: ProfileService, content: bytes = RESUME, filename: str = "cv.txt"
) -> uuid.UUID:
    uploaded = await profile.upload_resume(
        OWNER, filename=filename, content_type="text/plain", content=content
    )
    await profile.parse_resume(OWNER, uploaded.id)
    return uploaded.id


async def test_deleting_a_resume_removes_the_file_and_only_its_evidence() -> None:
    uow = FakeProfileUnitOfWork()
    profile, store = _service_with_store(uow)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")
    resume_id = await _upload_and_parse(profile)
    before = await profile.snapshot(OWNER)
    resume_facts = [e for e in before.evidence if e.source is EvidenceSource.RESUME]
    assert resume_facts
    uow.store.events.clear()

    await profile.delete_resume(OWNER, resume_id)

    after = await profile.snapshot(OWNER)
    assert {e.source for e in after.evidence} == {EvidenceSource.GITHUB}
    assert uow.store.resumes == {} and store.objects == {}
    assert after.version == before.version + 1 == await profile.version(OWNER)
    assert uow.store.events == [
        ProfileUpdated(
            owner_id=OWNER,
            source=EvidenceSource.RESUME,
            version=after.version,
            count=len(resume_facts),
        )
    ]


async def test_a_line_restated_by_a_newer_upload_belongs_to_that_upload() -> None:
    uow = FakeProfileUnitOfWork()
    profile, _ = _service_with_store(uow)
    older = await _upload_and_parse(profile)
    newer = await _upload_and_parse(profile)
    count = len((await profile.snapshot(OWNER)).evidence)

    # Removing the older copy keeps what the newer one still says...
    await profile.delete_resume(OWNER, older)
    assert len((await profile.snapshot(OWNER)).evidence) == count

    # ...and removing the newer one takes it away.
    await profile.delete_resume(OWNER, newer)
    assert (await profile.snapshot(OWNER)).evidence == ()


async def test_a_resume_that_is_not_yours_cannot_be_deleted() -> None:
    uow = FakeProfileUnitOfWork()
    profile, store = _service_with_store(uow)
    theirs = await profile.upload_resume(
        OTHER, filename="cv.txt", content_type="text/plain", content=RESUME
    )

    with pytest.raises(NotFoundError):
        await profile.delete_resume(OWNER, theirs.id)
    assert list(uow.store.resumes) == [theirs.id] and store.objects


# --- answers and the snapshot ----------------------------------------------


async def test_an_answer_becomes_user_answer_evidence() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    evidence = await profile.record_answer(
        OWNER, question_id="q1", question="Led a team?", answer=" Yes, six people. "
    )

    assert evidence.source is EvidenceSource.USER_ANSWER
    assert evidence.fact == "Led a team? — Yes, six people."
    assert await profile.evidence_ids(OWNER) == {str(evidence.id)}
    assert await profile.evidence_ids(OTHER) == set()


async def test_a_submit_of_answers_is_one_profile_update() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    stored = await profile.record_answers(
        OWNER,
        [
            AnswerRecord(question_id="q1", fact="On call? Yes, as primary"),
            AnswerRecord(question_id="q2", fact="Largest design? 4 to 10 engineers"),
        ],
    )

    assert [e.fact for e in stored] == [
        "On call? Yes, as primary",
        "Largest design? 4 to 10 engineers",
    ]
    assert {e.source for e in stored} == {EvidenceSource.USER_ANSWER}
    assert len([e for e in uow.store.events if type(e).__name__ == "ProfileUpdated"]) == 1


async def test_a_submit_with_no_answers_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).record_answers(OWNER, [])


async def test_an_empty_answer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).record_answer(
            OWNER, question_id="q1", question="?", answer="  "
        )


async def test_the_snapshot_lists_facts_newest_first_and_totals_the_timeline() -> None:
    """Newest first by the date each is shown with, undated last (ADR 0037),
    so a prompt that keeps only the first so many drops the oldest."""
    undated = replace(_draft("pr/2", "Reviewed the RFC"), observed_on=None)
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector([undated, _draft("pr/1")]))
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.record_answer(OWNER, question_id="q1", question="Q?", answer="A.")
    await profile.sync_connection(OWNER, "github")
    async with uow.for_owner(OWNER) as mine:
        await mine.positions.create(
            CareerPosition(
                id=uuid.uuid4(),
                owner_id=OWNER,
                title="Engineer",
                company="Acme",
                started_on=date(2020, 1, 1),
                ended_on=date(2022, 1, 1),
            )
        )

    snapshot = await profile.snapshot(OWNER)

    # The answer is dated today, the PR 2026-09-01, the review not at all.
    assert [(e.source, e.fact) for e in snapshot.evidence] == [
        (EvidenceSource.USER_ANSWER, "Q? — A."),
        (EvidenceSource.GITHUB, "Shipped the thing"),
        (EvidenceSource.GITHUB, "Reviewed the RFC"),
    ]
    assert snapshot.version == 2
    assert snapshot.total_experience_months == 24


async def test_an_analysis_replaces_the_timeline_and_moves_no_version() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    await profile.record_answer(OWNER, question_id="q1", question="Q?", answer="A.")
    before = await profile.version(OWNER)
    first = uuid.uuid4()
    await profile.replace_positions(
        OWNER, first, [PositionReading("Engineer", "Acme", date(2019, 1, 1), None, ("a1",))]
    )
    second = uuid.uuid4()

    await profile.replace_positions(
        OWNER,
        second,
        [PositionReading("Staff Engineer", "Kestrel", date(2022, 1, 1), None, ("a1",))],
    )

    snapshot = await profile.snapshot(OWNER)
    assert [(p.title, p.company) for p in snapshot.positions] == [("Staff Engineer", "Kestrel")]
    async with uow.for_owner(OWNER) as mine:
        [stored] = await mine.positions.get_list(CareerPositionFilter())
    assert (stored.skill_assessment_id, stored.evidence_ids) == (second, ("a1",))
    assert await profile.version(OWNER) == before
    assert (await profile.snapshot(OTHER)).positions == ()


async def test_a_resume_line_is_dated_by_the_upload_it_was_last_found_in() -> None:
    uow = FakeProfileUnitOfWork()
    profile, _ = _service_with_store(uow)
    older = await _upload_and_parse(profile)
    uow.store.resumes[older].created_at = datetime(2025, 5, 2, tzinfo=UTC)
    lines = (await profile.snapshot(OWNER)).evidence
    assert {e.stated_on for e in lines} == {date(2025, 5, 2)}
    assert {get_evidence_line(e).split(") ")[0] for e in lines} == {
        "(resume, from a résumé uploaded 2025-05-02"
    }

    newer = await _upload_and_parse(profile)
    uow.store.resumes[newer].created_at = datetime(2026, 9, 30, tzinfo=UTC)

    assert {e.stated_on for e in (await profile.snapshot(OWNER)).evidence} == {date(2026, 9, 30)}


# --- what is still running (ADR 0018) --------------------------------------


class _BrokenConnector(FakeConnector):
    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        raise RuntimeError("the connector fell over")


async def _connected(profile: ProfileService) -> None:
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )


async def test_a_requested_sync_shows_as_syncing_until_it_finishes() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector([_draft("pr/1")]))
    await _connected(profile)

    await profile.request_sync(OWNER, "github")
    syncing = (await profile.processing(OWNER)).syncing

    assert [p.label for p in syncing] == ["github"]
    await profile.sync_connection(OWNER, "github")
    assert (await profile.processing(OWNER)).syncing == ()


@pytest.mark.parametrize("connector", [FakeConnector(fails=True), _BrokenConnector()])
async def test_a_sync_that_fails_in_any_way_stops_showing_as_syncing(
    connector: FakeConnector,
) -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=connector)
    await _connected(profile)
    await profile.request_sync(OWNER, "github")

    with pytest.raises((UpstreamFailedError, RuntimeError)):
        await profile.sync_connection(OWNER, "github")

    (connection,) = uow.store.connections.values()
    assert connection.status is ConnectionStatus.FAILED and connection.last_error
    assert (await profile.processing(OWNER)).syncing == ()


async def test_a_sync_cannot_be_requested_for_a_source_that_is_not_connected() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeProfileUnitOfWork()).request_sync(OWNER, "github")


async def test_an_uploaded_resume_shows_as_parsing_until_it_is_parsed() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    uploaded = await profile.upload_resume(
        OWNER, filename="cv.txt", content_type="text/plain", content=RESUME
    )

    assert [p.label for p in (await profile.processing(OWNER)).parsing] == ["cv.txt"]
    await profile.parse_resume(OWNER, uploaded.id)
    assert (await profile.processing(OWNER)).parsing == ()


async def test_a_parse_that_stops_unexpectedly_is_recorded_and_still_raised() -> None:
    uow = FakeProfileUnitOfWork()
    store = FakeObjectStore()
    profile = ProfileService(
        uow,
        object_store=store,  # type: ignore[arg-type]
        connectors={},
        resume_max_bytes=10_000,
        resume_max_pages=5,
        http_timeout_seconds=1,
        user_agent="test",
    )
    uploaded = await profile.upload_resume(
        OWNER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    store.objects.clear()

    with pytest.raises(KeyError):
        await profile.parse_resume(OWNER, uploaded.id)

    (stored,) = uow.store.resumes.values()
    assert stored.status is ResumeStatus.FAILED and stored.parse_error
    assert (await profile.processing(OWNER)).parsing == ()
