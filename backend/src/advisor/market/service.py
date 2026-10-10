"""Companies, postings and crawl sources.

Two audiences with very different rights:

* ``MarketService`` — api and worker. Owner-zone reads and writes.
* ``CrawlIngest`` — the crawler deployable. Shared zone only. Its unit of work
  runs on the ``crawler_rw`` role, which has no grant on any user schema, so a
  mistake here fails at the database rather than leaking.

Both reach stored data only through the repository interfaces in
``advisor.market.domain`` (ADR 0010).

The domain value objects the crawler needs are re-exported here, because the
crawler may not import ``advisor.market.domain`` directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from advisor.market.baseline import BASELINE_SOURCES, BaselineSource
from advisor.market.domain import (
    MAX_TARGET_LOCATION,
    MAX_TARGET_LOCATIONS,
    Company,
    CompanyFilter,
    CrawlSource,
    CrawlSourceFilter,
    FreshWindows,
    JobPosting,
    JobPostingFilter,
    MarketPreference,
    MarketPreferenceFilter,
    MarketUnitOfWork,
    NormalizedPosting,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingHead,
    PostingScope,
    PostingStatus,
    SalaryBand,
    SalaryRange,
    SearchResultFilter,
    SearchScope,
    SharedMarket,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    TargetLocationError,
    TargetLocationsChanged,
    Visibility,
    band_from,
    canonical_key,
    chosen_target_locations,
    credited_source,
    in_market,
    names_every_word,
    normalize,
    normalize_title,
    remote_location,
    salary_in_text,
    search_scope,
    target_location_options,
    yearly_range,
)
from kernel.clock import utcnow
from kernel.errors import NotFoundError, ValidationError
from kernel.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "BASELINE_SOURCES",
    "MAX_TARGET_LOCATION",
    "MAX_TARGET_LOCATIONS",
    "BaselineSource",
    "CrawlIngest",
    "CrawlSourceView",
    "FreshWindows",
    "MarketScopeView",
    "MarketService",
    "NormalizedPosting",
    "PostingStatus",
    "PostingView",
    "SalaryBand",
    "SalaryRange",
    "SearchScope",
    "SourceKind",
    "SourceOrigin",
    "SourcesRequestView",
    "TargetLocationOptionView",
    "Visibility",
    "band_from",
    "canonical_key",
    "in_market",
    "names_every_word",
    "normalize_title",
    "remote_location",
    "salary_in_text",
    "search_scope",
    "yearly_range",
]


@dataclass(frozen=True, slots=True)
class CrawlSourceView:
    id: uuid.UUID
    kind: str
    endpoint: str
    company_id: uuid.UUID | None
    company_name: str | None
    market: str | None


@dataclass(frozen=True, slots=True)
class TargetLocationOptionView:
    """One place the user may pick: "remote", "region" or "country"."""

    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class SourcesRequestView:
    """What one build needs from the market: every source it reads, and those
    of them it has to wait for (ADR 0027)."""

    needed: tuple[uuid.UUID, ...]
    due: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class MarketScopeView:
    """The user's target locations and the open postings they take in. With
    none chosen, the scope is the platform's baseline."""

    target_locations: list[str]
    open_posting_count: int


@dataclass(frozen=True, slots=True)
class PostingView:
    id: uuid.UUID
    company_name: str
    title: str
    location: str | None
    url: str | None
    description: str
    visibility: Visibility
    salary: SalaryRange | None
    # Shared postings only; a pasted JD names its company but has no row there.
    company_id: uuid.UUID | None = None
    # Which kind of source it was crawled from (atsBoard, jsonLd, publicApi);
    # None for a pasted JD, which was not crawled at all.
    source_kind: str | None = None
    # The job site this opening must be credited to wherever it is shown, with
    # its link (ADR 0025); None when the link is the employer's own.
    credited_to: str | None = None
    # The day it was posted, as its source states it, else the day it was
    # first fetched; None for a pasted JD.
    posted_on: date | None = None


@dataclass(frozen=True, slots=True)
class PostingHeadView:
    """A shared posting without its description: what matching, counting and
    listing read (``posting_heads_in_scope``). ``postings_by_id`` reads the
    description for the few a prompt needs."""

    id: uuid.UUID
    company_name: str
    title: str
    location: str | None
    url: str | None
    visibility: Visibility
    salary: SalaryRange | None
    company_id: uuid.UUID | None = None
    source_kind: str | None = None
    credited_to: str | None = None
    posted_on: date | None = None


class CrawlIngest:
    """What the crawler may do. Shared zone only; no user data, ever.

    The crawler fetches only what a build is waiting for (ADR 0027): a source
    is due while a build needs it and its last fetch is too old to reuse.
    Nothing it stores is announced, because nothing it learns is resolved to
    the users it concerns.
    """

    def __init__(self, uow: MarketUnitOfWork) -> None:
        self._uow = uow

    async def due_sources(self) -> list[CrawlSourceView]:
        """Active sources a build is waiting for."""
        return await self._sources(CrawlSourceFilter(status=SourceStatus.ACTIVE, is_due=True))

    async def _sources(self, filter: CrawlSourceFilter) -> list[CrawlSourceView]:
        async with self._uow.shared() as market:
            sources = await market.sources.get_list(filter)
            names = await _company_names(market, {s.company_id for s in sources})
        return [
            CrawlSourceView(
                id=source.id,
                kind=source.kind,
                endpoint=source.endpoint,
                company_id=source.company_id,
                company_name=names.get(source.company_id) if source.company_id else None,
                market=source.market,
            )
            for source in sources
        ]

    async def record_crawl(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None = None,
    ) -> tuple[int, int]:
        """Store one fetch. Returns (upserted, expired).

        A board lists everything its company has, so what it no longer lists
        is expired. A search shows one page, so its fetch replaces its result
        list instead and expires nothing: a job missing from the page was
        usually pushed off it, not closed (ADR 0027). A failed fetch changes
        neither.
        """
        now = utcnow()
        async with self._uow.shared() as market:
            source = await market.sources.get(source_id)
            if source is None:
                raise NotFoundError("crawl source not found", source_id=str(source_id))
            source.record_fetch(now, error)
            await market.sources.update(source)
            if error is not None:
                return (0, 0)

            seen: dict[str, uuid.UUID] = {}
            for posting in postings:
                company = await _ensure_company(market, posting.company_name)
                stored = await _upsert_posting(market, source_id, company.id, posting)
                seen.setdefault(posting.canonical_key, stored)

            if source.is_search:
                await market.search_results.replace(source_id, list(seen.values()), at=now)
                return (len(seen), 0)
            expired = await market.postings.expire_unseen(source_id, set(seen))
            return (len(seen), expired)

    async def mark_fetched(self, source_ids: Iterable[uuid.UUID]) -> None:
        """These sources' fetches are stored and embedded: the builds waiting
        for them may start (ADR 0027)."""
        wanted = tuple(source_ids)
        if not wanted:
            return
        async with self._uow.shared() as market:
            for source in await market.sources.get_list(CrawlSourceFilter(ids=wanted)):
                if source.is_due:
                    source.fetched()
                    await market.sources.update(source)

    async def retire_idle_searches(self, *, idle_since: datetime) -> int:
        """Stop fetching the searches no build has needed since ``idle_since``,
        and empty their result lists, so what they found leaves every scope
        and is thinned later. Returns how many were retired."""
        retired = 0
        async with self._uow.shared() as market:
            for source in await market.sources.get_list(
                CrawlSourceFilter(
                    status=SourceStatus.ACTIVE, is_search=True, requested_before=idle_since
                )
            ):
                if not source.retire_idle():
                    continue
                await market.sources.update(source)
                await market.search_results.replace(source.id, [], at=utcnow())
                retired += 1
        return retired

    async def thin_unheld_postings(self, *, unseen_since: datetime) -> int:
        """Drop the description and embedding of postings nothing holds and
        nobody has seen since ``unseen_since``. The rows stay, so a Target
        that names one still finds it (ADR 0027). Returns how many."""
        async with self._uow.shared() as market:
            return await market.postings.thin_unheld(unseen_since=unseen_since, at=utcnow())

    async def postings_needing_embeddings(
        self, model_name: str, limit: int = 200
    ) -> list[tuple[uuid.UUID, str]]:
        async with self._uow.shared() as market:
            postings = await market.postings.get_list(
                JobPostingFilter(missing_embedding_for=model_name), page_size=limit
            )
        # Title carries most of the signal, so it leads, twice.
        return [(p.id, "\n".join(part for part in _embedding_parts(p) if part)) for p in postings]

    async def store_embeddings(
        self, model_name: str, vectors: dict[uuid.UUID, list[float]]
    ) -> None:
        async with self._uow.shared() as market:
            for posting_id, vector in vectors.items():
                await market.embeddings.create(
                    PostingEmbedding(posting_id=posting_id, model_name=model_name, vector=vector)
                )


class MarketService:
    """Target locations, the postings in scope, and the sources a build needs."""

    def __init__(self, uow: MarketUnitOfWork, *, windows: FreshWindows) -> None:
        self._uow = uow
        self._windows = windows

    def target_location_options(self) -> list[TargetLocationOptionView]:
        """The places a user may pick from: "Remote", the regions, then the
        countries, each group A to Z (ADR 0026)."""
        return [
            TargetLocationOptionView(name=option.name, kind=str(option.kind))
            for option in target_location_options()
        ]

    async def target_locations(self, owner_id: uuid.UUID) -> list[str]:
        """Where the user wants to work, alphabetically."""
        async with self._uow.for_owner(owner_id) as mine:
            chosen = await mine.markets.get_list(MarketPreferenceFilter())
        return sorted(m.market for m in chosen)

    async def set_target_locations(self, owner_id: uuid.UUID, locations: list[str]) -> list[str]:
        """Replace the user's target locations with ``locations``: one to three
        places from the list, or none to fall back to the baseline (domain
        decision 21, ADR 0026).

        A change is announced once, with the whole new set, so the role map is
        rebuilt on the new scope. Saving the same set again announces nothing.
        """
        try:
            wanted = tuple(sorted(chosen_target_locations(locations)))
        except TargetLocationError as exc:
            raise ValidationError(str(exc)) from exc
        async with self._uow.for_owner(owner_id) as mine:
            current = await mine.markets.get_list(MarketPreferenceFilter())
            if tuple(sorted(m.market for m in current)) == wanted:
                return list(wanted)
            for preference in current:
                await mine.markets.delete(preference.id)
            for value in wanted:
                await mine.markets.create(MarketPreference.chosen(owner_id=owner_id, market=value))
            mine.record(TargetLocationsChanged(owner_id=owner_id, locations=wanted))
        return list(wanted)

    async def has_searchable_place(self, owner_id: uuid.UUID) -> bool:
        """Whether a build for this user searches a job API: one of their
        target locations is a country or "Remote" (ADR 0026)."""
        places = await self.target_locations(owner_id)
        return any(search_scope(place) is not None for place in places)

    async def scope(self, owner_id: uuid.UUID) -> MarketScopeView:
        """How much of the market the user's target locations take in."""
        locations = await self.target_locations(owner_id)
        heads = await self.posting_heads_in_scope(owner_id)
        return MarketScopeView(target_locations=locations, open_posting_count=len(heads))

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        """Every shared posting this user's role map is built from: the open
        postings in their target locations.

        A user who has chosen no location gets the platform's baseline postings
        instead (domain decision 15), so a first role map has something to
        group. Pasted JDs are not here: each is a posting of the user's own,
        kept by Target (ADR 0033), and never on the map.
        """
        scope = await self._posting_scope(owner_id)

        async with self._uow.shared() as market:
            postings = await market.postings.get_open_in_scope(scope)
            names = await _company_names(market, {p.company_id for p in postings})

        return [_shared_posting_view(p, names.get(p.company_id, "")) for p in postings]

    async def posting_heads_in_scope(
        self, owner_id: uuid.UUID, posting_ids: Sequence[uuid.UUID] | None = None
    ) -> list[PostingHeadView]:
        """``postings_in_scope`` without descriptions, in the same order;
        only ``posting_ids`` among them when given.

        What a build matches and a role map counts: a scope can be thousands
        of postings, and only the few a prompt reads need their text
        (``postings_by_id``). A role's openings are its members still in
        scope, so asking for those ids reads a few dozen, not the market.
        """
        scope = await self._posting_scope(owner_id)
        ids = tuple(posting_ids) if posting_ids is not None else None
        async with self._uow.shared() as market:
            heads = await market.postings.get_open_heads_in_scope(scope, ids)
            names = await _company_names(market, {h.company_id for h in heads})
        return [_posting_head_view(h, names.get(h.company_id, "")) for h in heads]

    async def postings_by_id(self, posting_ids: Sequence[uuid.UUID]) -> list[PostingView]:
        """These shared postings with their descriptions, in the order asked
        for; an id with no posting is left out."""
        if not posting_ids:
            return []
        async with self._uow.shared() as market:
            postings = await market.postings.get_list(JobPostingFilter(ids=tuple(posting_ids)))
            names = await _company_names(market, {p.company_id for p in postings})
        by_id = {p.id: p for p in postings}
        return [
            _shared_posting_view(by_id[i], names.get(by_id[i].company_id, ""))
            for i in posting_ids
            if i in by_id
        ]

    async def scope_with_vectors(
        self, owner_id: uuid.UUID, model_name: str
    ) -> list[tuple[str, PostingHeadView, list[float] | None]]:
        """Every posting in this user's scope, keyed by its shared id, with the
        embedding the crawler made for it, or ``None`` where it has not yet.
        Heads only: no description crosses."""
        heads = await self.posting_heads_in_scope(owner_id)
        vectors = await self.vectors_by_id([h.id for h in heads], model_name)
        return [(str(h.id), h, vectors.get(h.id)) for h in heads]

    async def vectors_by_id(
        self, posting_ids: Sequence[uuid.UUID], model_name: str
    ) -> dict[uuid.UUID, list[float]]:
        """The crawler's embedding of each of these postings that has one."""
        if not posting_ids:
            return {}
        async with self._uow.shared() as market:
            embedded = await market.embeddings.get_list(
                PostingEmbeddingFilter(posting_ids=tuple(posting_ids), model_name=model_name)
            )
        return {e.posting_id: e.vector for e in embedded}

    async def _posting_scope(self, owner_id: uuid.UUID) -> PostingScope:
        return PostingScope(markets=tuple(await self.target_locations(owner_id)))

    async def seed_baseline(
        self, sources: tuple[BaselineSource, ...] = BASELINE_SOURCES
    ) -> tuple[int, int]:
        """Make ``market.crawl_source`` match the baseline list. Idempotent.

        Returns (active, retired). An entry no longer listed is retired, never
        deleted: the postings it found keep a source that can expire them.
        A demand source with the same endpoint becomes a baseline one; it is
        the same board either way.
        """
        wanted = {(s.kind, s.endpoint) for s in sources}
        async with self._uow.shared() as market:
            for listed in sources:
                company = await _ensure_company(market, listed.company_name)
                source = _first(
                    await market.sources.get_list(
                        CrawlSourceFilter(kind=listed.kind, endpoint=listed.endpoint), page_size=1
                    )
                )
                if source is None:
                    await market.sources.create(
                        CrawlSource.board(
                            kind=listed.kind,
                            endpoint=listed.endpoint,
                            company_id=company.id,
                            origin=SourceOrigin.BASELINE,
                        )
                    )
                else:
                    source.make_baseline(company.id)
                    await market.sources.update(source)

            retired = 0
            # The baseline list is short by design (see advisor.market.baseline).
            for source in await market.sources.get_list(
                CrawlSourceFilter(origin=SourceOrigin.BASELINE)
            ):
                if (source.kind, source.endpoint) not in wanted and source.retire():
                    await market.sources.update(source)
                    retired += 1
        return len(sources), retired

    async def request_sources(
        self,
        *,
        titles: Sequence[str],
        places: Sequence[str],
        at: datetime | None = None,
    ) -> SourcesRequestView:
        """The sources one build needs, each marked asked for, and due when it
        isn't fresh (ADR 0027).

        They are a search of each job title in each place a search covers (a
        country, or "Remote"; a region adds none), and the baseline boards. A
        search that does not exist yet is made as an ownerless ``demand``
        source: only titles and places reach here, never who asked.
        """
        from advisor.market.crawling.adapters import SEARCH_ADAPTERS

        now = at or utcnow()
        searches = _searches(SEARCH_ADAPTERS, titles, places)
        needed: list[uuid.UUID] = []
        due: list[uuid.UUID] = []
        async with self._uow.shared() as market:
            for (kind, endpoint), place in sorted(searches.items()):
                await market.sources.create_if_absent(
                    CrawlSource.search(kind=kind, endpoint=endpoint, market=place, at=now)
                )
            sources = [
                source
                for (kind, endpoint) in sorted(searches)
                for source in await market.sources.get_list(
                    CrawlSourceFilter(kind=kind, endpoint=endpoint), page_size=1
                )
            ]
            sources += await market.sources.get_list(
                CrawlSourceFilter(status=SourceStatus.ACTIVE, origin=SourceOrigin.BASELINE)
            )
            for source in {source.id: source for source in sources}.values():
                needed.append(source.id)
                if source.needed(now, self._windows):
                    due.append(source.id)
                await market.sources.update(source)
        log.info("market.sources_requested", needed=len(needed), due=len(due))
        return SourcesRequestView(needed=tuple(needed), due=tuple(due))

    async def pending_sources(self, source_ids: Sequence[uuid.UUID]) -> tuple[uuid.UUID, ...]:
        """Which of these sources are still waiting to be fetched."""
        if not source_ids:
            return ()
        async with self._uow.shared() as market:
            waiting = await market.sources.get_list(
                CrawlSourceFilter(ids=tuple(source_ids), is_due=True)
            )
        return tuple(source.id for source in waiting)

    async def oldest_fetch(self, source_ids: Sequence[uuid.UUID]) -> datetime | None:
        """When the stalest of these sources was last fetched: how old the
        market a build used is. ``None`` when none has been fetched."""
        if not source_ids:
            return None
        async with self._uow.shared() as market:
            found = await market.sources.get_list(CrawlSourceFilter(ids=tuple(source_ids)))
        fetched = [s.last_fetched_at for s in found if s.last_fetched_at is not None]
        return min(fetched) if fetched else None

    async def search_results(
        self, *, titles: Sequence[str], places: Sequence[str]
    ) -> dict[str, list[uuid.UUID]]:
        """For each title, the postings on the current result lists of its
        searches in these places, best first: what the search found for it."""
        from advisor.market.crawling.adapters import SEARCH_ADAPTERS

        by_title: dict[str, list[uuid.UUID]] = {title: [] for title in titles}
        async with self._uow.shared() as market:
            for title in titles:
                for kind, endpoint in _searches(SEARCH_ADAPTERS, [title], places):
                    source = _first(
                        await market.sources.get_list(
                            CrawlSourceFilter(kind=kind, endpoint=endpoint), page_size=1
                        )
                    )
                    if source is None:
                        continue
                    listed = await market.search_results.get_list(
                        SearchResultFilter(crawl_source_ids=(source.id,))
                    )
                    for result in sorted(listed, key=lambda r: r.rank):
                        if result.job_posting_id not in by_title[title]:
                            by_title[title].append(result.job_posting_id)
        return by_title

    async def salary_band(self, owner_id: uuid.UUID, posting_ids: list[uuid.UUID]) -> object:
        async with self._uow.shared() as market:
            paying = await market.postings.get_list(
                JobPostingFilter(ids=tuple(posting_ids), has_salary=True)
            )
        ranges = [p.salary for p in paying if p.salary is not None]
        return band_from([(r.min_amount, r.max_amount, r.currency) for r in ranges])


# --- helpers ---------------------------------------------------------------


def _first[T](items: list[T]) -> T | None:
    return items[0] if items else None


async def _company_names(
    market: SharedMarket, company_ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    ids = tuple(i for i in company_ids if i is not None)
    if not ids:
        return {}
    companies = await market.companies.get_list(CompanyFilter(ids=ids))
    return {c.id: c.name for c in companies}


async def _ensure_company(market: SharedMarket, name: str) -> Company:
    existing = _first(
        await market.companies.get_list(CompanyFilter(normalized_name=normalize(name)), page_size=1)
    )
    if existing is not None:
        return existing
    return await market.companies.create(Company.named(name))


async def _upsert_posting(
    market: SharedMarket,
    source_id: uuid.UUID,
    company_id: uuid.UUID,
    posting: NormalizedPosting,
) -> uuid.UUID:
    """Store one posting, new or seen again. Returns its id."""
    now = utcnow()
    existing = _first(
        await market.postings.get_list(
            JobPostingFilter(canonical_key=posting.canonical_key), page_size=1
        )
    )
    if existing is None:
        created = await market.postings.create(
            JobPosting.first_seen(posting, company_id=company_id, source_id=source_id, at=now)
        )
        return created.id
    existing.seen_again(posting, source_id=source_id, at=now)
    await market.postings.update(existing)
    return existing.id


class _SearchAdapter(Protocol):
    name: str

    def search_endpoint(self, title: str, scope: SearchScope) -> str | None: ...


def _searches(
    adapters: Iterable[_SearchAdapter], titles: Iterable[str], places: Iterable[str]
) -> dict[tuple[str, str], str]:
    """Every (kind, endpoint) to search for these titles in these places,
    with the place each is filed under. A place no search covers adds none."""
    scopes = {scope for place in places if (scope := search_scope(place)) is not None}
    found: dict[tuple[str, str], str] = {}
    for adapter in adapters:
        for scope in sorted(scopes, key=lambda s: s.label):
            for title in titles:
                endpoint = adapter.search_endpoint(title, scope)
                if endpoint is not None:
                    found[(adapter.name, endpoint)] = scope.label
    return found


def _embedding_parts(posting: JobPosting) -> tuple[str | None, ...]:
    return (posting.title, posting.title, posting.location, posting.description)


def _posting_head_view(head: PostingHead, company_name: str) -> PostingHeadView:
    return PostingHeadView(
        id=head.id,
        company_name=company_name,
        title=head.title,
        location=head.location,
        url=head.url,
        visibility=Visibility.SHARED,
        salary=head.salary,
        company_id=head.company_id,
        source_kind=head.source_kind,
        credited_to=credited_source(head.url),
        posted_on=head.posted_on or head.first_seen_at.date(),
    )


def _shared_posting_view(posting: JobPosting, company_name: str) -> PostingView:
    return PostingView(
        id=posting.id,
        company_name=company_name,
        title=posting.title,
        location=posting.location,
        url=posting.url,
        description=posting.description,
        visibility=Visibility.SHARED,
        salary=posting.salary,
        company_id=posting.company_id,
        source_kind=posting.source_kind,
        credited_to=credited_source(posting.url),
        posted_on=posting.posted_on or posting.first_seen_at.date(),
    )
