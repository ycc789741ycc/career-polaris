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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.market.baseline import BASELINE_SOURCES, BaselineSource
from advisor.market.domain import (
    MAX_TARGET_LOCATION,
    MAX_TARGET_LOCATIONS,
    SEARCH_SOURCE_IDLE_WEEKS,
    Company,
    CompanyFilter,
    CrawlSource,
    CrawlSourceFilter,
    JobPosting,
    JobPostingFilter,
    MarketPreference,
    MarketPreferenceFilter,
    MarketUnitOfWork,
    NormalizedPosting,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingsChanged,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    SalaryBand,
    SalaryRange,
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
    scope_names,
    search_scope,
    target_location_options,
)
from kernel.clock import utcnow
from kernel.errors import NotFoundError, ValidationError

__all__ = [
    "BASELINE_SOURCES",
    "MAX_TARGET_LOCATION",
    "MAX_TARGET_LOCATIONS",
    "BaselineSource",
    "CrawlIngest",
    "CrawlSourceView",
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


class CrawlIngest:
    """What the crawler may do. Shared zone only; no user data, ever."""

    def __init__(self, uow: MarketUnitOfWork) -> None:
        self._uow = uow

    async def due_sources(self) -> list[CrawlSourceView]:
        # Every active source is crawled each run, so the set is read whole.
        return await self._sources(CrawlSourceFilter(status=SourceStatus.ACTIVE))

    async def new_sources(self) -> list[CrawlSourceView]:
        """Active sources no crawl has fetched yet: a search a user's
        candidates just asked for, or a board discovery just found. Crawled
        between the weekly runs, so nobody waits a week for them (ADR 0025)."""
        return await self._sources(CrawlSourceFilter(status=SourceStatus.ACTIVE, is_unfetched=True))

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

    async def retire_idle_searches(self, now: datetime) -> int:
        """Stop crawling the searches nobody's candidates have asked for in
        ``SEARCH_SOURCE_IDLE_WEEKS``, and expire what they found: with no
        crawl left to notice a posting closing, it would stay open for ever.
        Returns how many were retired."""
        idle_since = now - timedelta(weeks=SEARCH_SOURCE_IDLE_WEEKS)
        retired = 0
        async with self._uow.shared() as market:
            for source in await market.sources.get_list(
                CrawlSourceFilter(status=SourceStatus.ACTIVE, requested_before=idle_since)
            ):
                if not source.retire():
                    continue
                await market.sources.update(source)
                expired = await market.postings.expire_unseen(source.id, set())
                if expired and source.market:
                    market.record(
                        PostingsChanged(
                            company_id=None, market=source.market, seen=0, expired=expired
                        )
                    )
                retired += 1
        return retired

    async def announce_markets(self, markets: Iterable[str]) -> None:
        """Say once per place that its postings changed, for the searches
        stored with ``record_search_crawl``: a place's searches are crawled
        together, and one announcement is one role-map rebuild."""
        async with self._uow.shared() as market:
            for name in sorted(set(markets)):
                market.record(PostingsChanged(company_id=None, market=name, seen=0, expired=0))

    async def record_crawl(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None = None,
    ) -> tuple[int, int]:
        """Upsert what was seen, expire what was not, and announce it.
        Returns (upserted, expired)."""
        seen, expired, _new = await self._record(source_id, postings, error=error, announce=True)
        return (seen, expired)

    async def record_search_crawl(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None = None,
    ) -> tuple[int, int, bool]:
        """Store one search's postings without announcing them. Returns
        (upserted, expired, changed): ``changed`` is whether an opening
        appeared or went, which is when the place is worth announcing, once,
        with ``announce_markets``. A crawl that finds the same openings again
        rebuilds nobody's role map."""
        seen, expired, new = await self._record(source_id, postings, error=error, announce=False)
        return (seen, expired, bool(new or expired))

    async def _record(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None,
        announce: bool,
    ) -> tuple[int, int, int]:
        """(seen, expired, new) for one source's crawl."""
        async with self._uow.shared() as market:
            source = await market.sources.get(source_id)
            if source is None:
                raise NotFoundError("crawl source not found", source_id=str(source_id))
            source.record_fetch(utcnow(), error)
            await market.sources.update(source)
            if error is not None:
                return (0, 0, 0)

            seen_keys: set[str] = set()
            new = 0
            for posting in postings:
                company = await _ensure_company(market, posting.company_name)
                new += await _upsert_posting(market, source_id, company.id, posting)
                seen_keys.add(posting.canonical_key)

            expired = await market.postings.expire_unseen(source_id, seen_keys)

            if announce:
                market.record(
                    PostingsChanged(
                        company_id=source.company_id,
                        market=source.market,
                        seen=len(seen_keys),
                        expired=expired,
                    )
                )
            return (len(seen_keys), expired, new)

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
    """Target locations and pasted JDs. Owner zone."""

    def __init__(self, uow: MarketUnitOfWork) -> None:
        self._uow = uow

    async def owners_affected_by(self, *, market: str | None = None) -> list[uuid.UUID]:
        """The users whose target locations name this market.

        A location names it when it contains every word of the market, or of
        another name for the same country: "Remote Taiwan" names "Taiwan", and
        "UK" names "United Kingdom". A search is filed under one name for a
        place that users spell several ways (ADR 0025).

        The only cross-user read in the system, through the fan-out transaction
        and its SELECT-only policy. The crawler cannot answer this — it has no
        grant on any user schema — so the worker's dispatcher asks here when a
        market changes (docs/architecture.md section 2).
        """
        if not market:
            return []
        async with self._uow.fanout() as everyone:
            choosing = await everyone.markets.get_list(
                MarketPreferenceFilter(names_any_of=scope_names(market))
            )
        return sorted({m.owner_id for m in choosing})

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

    async def scope(self, owner_id: uuid.UUID) -> MarketScopeView:
        """How much of the market the user's target locations take in."""
        locations = await self.target_locations(owner_id)
        postings = await self.postings_in_scope(owner_id)
        return MarketScopeView(target_locations=locations, open_posting_count=len(postings))

    async def paste_job_description(
        self,
        owner_id: uuid.UUID,
        *,
        company_name: str,
        title: str,
        location: str | None,
        description: str,
        url: str | None = None,
    ) -> PostingView:
        """Store a JD the user pasted. Private to them, always."""
        if not description.strip():
            raise ValidationError("a job description is required")
        if not title.strip():
            raise ValidationError("a job title is required")

        key = canonical_key(company=company_name, title=title, location=location)

        # A private copy may link to a matching crawled posting so the user gets
        # weekly updates. Nothing flows back the other way.
        async with self._uow.shared() as market:
            match = _first(
                await market.postings.get_list(JobPostingFilter(canonical_key=key), page_size=1)
            )

        async with self._uow.for_owner(owner_id) as mine:
            created = await mine.private_postings.create(
                PrivateJobPosting.pasted(
                    owner_id=owner_id,
                    company_name=company_name,
                    title=title,
                    location=location,
                    description=description,
                    url=url,
                    shared_posting_id=match.id if match is not None else None,
                )
            )
        return _private_posting_view(created)

    async def private_postings(self, owner_id: uuid.UUID) -> list[PostingView]:
        """Newest first. One user's pasted JDs: a small set, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            pasted = await mine.private_postings.get_list(PrivateJobPostingFilter())
        return [_private_posting_view(p) for p in pasted]

    async def private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> PostingView:
        """One pasted JD. Another user's is simply not found: it is behind RLS."""
        async with self._uow.for_owner(owner_id) as mine:
            posting = await mine.private_postings.get(posting_id)
            if posting is None:
                raise NotFoundError("job description not found", posting_id=str(posting_id))
            return _private_posting_view(posting)

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        """Every shared posting this user's role map is built from: the open
        postings in their target locations.

        A user who has chosen no location gets the platform's baseline postings
        instead (domain decision 15), so a first role map has something to
        group. Pasted JDs are not here: each belongs to the custom role it came
        with (domain decision 25), and never to a cluster.
        """
        scope = PostingScope(markets=tuple(await self.target_locations(owner_id)))

        async with self._uow.shared() as market:
            postings = await market.postings.get_open_in_scope(scope)
            names = await _company_names(market, {p.company_id for p in postings})

        return [_shared_posting_view(p, names.get(p.company_id, "")) for p in postings]

    async def scope_with_vectors(
        self, owner_id: uuid.UUID, model_name: str
    ) -> list[tuple[str, PostingView, list[float] | None]]:
        """Every posting in this user's scope, keyed by its shared id, with the
        embedding the crawler made for it, or ``None`` where it has not yet."""
        postings = await self.postings_in_scope(owner_id)
        vectors: dict[uuid.UUID, list[float]] = {}
        if postings:
            async with self._uow.shared() as market:
                embedded = await market.embeddings.get_list(
                    PostingEmbeddingFilter(
                        posting_ids=tuple(p.id for p in postings), model_name=model_name
                    )
                )
            vectors = {e.posting_id: e.vector for e in embedded}
        return [(str(p.id), p, vectors.get(p.id)) for p in postings]

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

    async def register_board(self, company_id: uuid.UUID, *, kind: str, endpoint: str) -> None:
        """Crawl a board that discovery found for a company, as a ``demand``
        source with no owner, unless the endpoint is already known."""
        async with self._uow.shared() as market:
            if await market.sources.get_count(CrawlSourceFilter(endpoint=endpoint)) == 0:
                await market.sources.create(
                    CrawlSource.board(
                        kind=kind,
                        endpoint=endpoint,
                        company_id=company_id,
                        origin=SourceOrigin.DEMAND,
                    )
                )

    async def request_searches(
        self, *, kind: str, searches: Mapping[str, str], at: datetime | None = None
    ) -> int:
        """Make sure each search is crawled: ``searches`` maps a search
        endpoint to the place it searches (ADR 0025). Returns how many are new.

        A search is a ``demand`` source with no owner. One that exists is only
        marked as asked for again, which keeps it crawled, so two users whose
        analyses recommend the same title in the same place share it and the
        row says nothing about either.
        """
        now = at or utcnow()
        created = 0
        async with self._uow.shared() as market:
            for endpoint, place in sorted(searches.items()):
                source = _first(
                    await market.sources.get_list(
                        CrawlSourceFilter(kind=kind, endpoint=endpoint), page_size=1
                    )
                )
                if source is None:
                    await market.sources.create(
                        CrawlSource.search(kind=kind, endpoint=endpoint, market=place, at=now)
                    )
                    created += 1
                else:
                    source.requested(now)
                    await market.sources.update(source)
        return created

    async def company_named(self, name: str) -> uuid.UUID:
        """The shared company with this name, recorded if it is new. A company
        holds no user data, so naming one leaves no trace of who named it."""
        if not name.strip():
            raise ValidationError("a company name is required")
        async with self._uow.shared() as market:
            return (await _ensure_company(market, name.strip())).id

    async def company_needing_source(self, company_id: uuid.UUID, fallback_name: str) -> str | None:
        """The name to look for a board under, or None when the company already
        has a crawl source."""
        async with self._uow.shared() as market:
            if await market.sources.get_count(CrawlSourceFilter(company_id=company_id)) > 0:
                return None
            company = await market.companies.get(company_id)
            return company.name if company is not None else fallback_name

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
) -> bool:
    """Store one posting. Returns whether it is new or open again."""
    now = utcnow()
    existing = _first(
        await market.postings.get_list(
            JobPostingFilter(canonical_key=posting.canonical_key), page_size=1
        )
    )
    if existing is None:
        await market.postings.create(
            JobPosting.first_seen(posting, company_id=company_id, source_id=source_id, at=now)
        )
        return True
    reopened = existing.status is not PostingStatus.OPEN
    existing.seen_again(posting, source_id=source_id, at=now)
    await market.postings.update(existing)
    return reopened


def _embedding_parts(posting: JobPosting) -> tuple[str | None, ...]:
    return (posting.title, posting.title, posting.location, posting.description)


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
    )


def _private_posting_view(posting: PrivateJobPosting) -> PostingView:
    return PostingView(
        id=posting.id,
        company_name=posting.company_name,
        title=posting.title,
        location=posting.location,
        url=posting.url,
        description=posting.description,
        visibility=Visibility.PRIVATE,
        salary=None,
    )
