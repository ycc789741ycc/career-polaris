"""SQLAlchemy implementations of the market's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Each
class here names its model, maps rows to entities and back, and turns its
filter's set fields into conditions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import Date, and_, cast, delete, exists, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.market.domain import (
    ACCENT_FOLDS,
    WORLDWIDE_WORDS,
    Company,
    CompanyFilter,
    CompanyRepository,
    CrawlSource,
    CrawlSourceFilter,
    CrawlSourceRepository,
    JobPosting,
    JobPostingFilter,
    JobPostingRepository,
    MarketPreference,
    MarketPreferenceFilter,
    MarketPreferenceRepository,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingEmbeddingRepository,
    PostingHead,
    PostingScope,
    PostingStatus,
    SearchResult,
    SearchResultFilter,
    SearchResultRepository,
    SourceOrigin,
    market_words,
    place_names,
    search_scope,
    target_location_option,
)
from advisor.market.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository

# --- shared zone -----------------------------------------------------------


class SqlAlchemyCompanyRepository(
    SqlAlchemyRepository[Company, models.Company, CompanyFilter],
    CompanyRepository,
):
    model = models.Company
    id_column = models.Company.id
    created_column = models.Company.created_at
    noun = "company"

    def to_entity(self, row: models.Company) -> Company:
        return mappers.company(row)

    def to_row(self, entity: Company) -> models.Company:
        return mappers.company_row(entity)

    def apply(self, row: models.Company, entity: Company) -> None:
        mappers.apply_company(row, entity)

    def id_of(self, entity: Company) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CompanyFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.ids is not None:
            found.append(models.Company.id.in_(filter.ids))
        if filter.normalized_name is not None:
            found.append(models.Company.normalized_name == filter.normalized_name)
        return found


class SqlAlchemyCrawlSourceRepository(
    SqlAlchemyRepository[CrawlSource, models.CrawlSource, CrawlSourceFilter],
    CrawlSourceRepository,
):
    model = models.CrawlSource
    id_column = models.CrawlSource.id
    created_column = models.CrawlSource.created_at
    noun = "crawl source"

    def to_entity(self, row: models.CrawlSource) -> CrawlSource:
        return mappers.crawl_source(row)

    def to_row(self, entity: CrawlSource) -> models.CrawlSource:
        return mappers.crawl_source_row(entity)

    def apply(self, row: models.CrawlSource, entity: CrawlSource) -> None:
        mappers.apply_crawl_source(row, entity)

    def id_of(self, entity: CrawlSource) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CrawlSourceFilter) -> list[ColumnElement[bool]]:
        source = models.CrawlSource
        found: list[ColumnElement[bool]] = []
        if filter.status is not None:
            found.append(source.status == str(filter.status))
        if filter.origin is not None:
            found.append(source.origin == str(filter.origin))
        if filter.company_id is not None:
            found.append(source.company_id == filter.company_id)
        if filter.kind is not None:
            found.append(source.kind == filter.kind)
        if filter.endpoint is not None:
            found.append(source.endpoint == filter.endpoint)
        if filter.ids is not None:
            found.append(source.id.in_(filter.ids))
        if filter.is_due is not None:
            due = source.due_at.is_not(None)
            found.append(due if filter.is_due else ~due)
        if filter.is_search is not None:
            # A search is filed under its place; a company's board has none.
            search = source.market.is_not(None)
            found.append(search if filter.is_search else ~search)
        if filter.requested_before is not None:
            found.append(source.last_requested_at < filter.requested_before)
        return found

    async def create_if_absent(self, source: CrawlSource) -> bool:
        row = mappers.crawl_source_row(source)
        values = {
            column.key: getattr(row, column.key)
            for column in models.CrawlSource.__table__.columns
            if getattr(row, column.key, None) is not None
        }
        result = await self._session.execute(
            pg_insert(models.CrawlSource)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_crawl_source_kind")
        )
        return bool(getattr(result, "rowcount", 0))


class SqlAlchemyJobPostingRepository(
    SqlAlchemyRepository[JobPosting, models.JobPosting, JobPostingFilter],
    JobPostingRepository,
):
    model = models.JobPosting
    id_column = models.JobPosting.id
    created_column = models.JobPosting.created_at
    noun = "job posting"

    def to_entity(self, row: models.JobPosting) -> JobPosting:
        return mappers.job_posting(row)

    def to_row(self, entity: JobPosting) -> models.JobPosting:
        return mappers.job_posting_row(entity)

    def apply(self, row: models.JobPosting, entity: JobPosting) -> None:
        mappers.apply_job_posting(row, entity)

    def id_of(self, entity: JobPosting) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: JobPostingFilter) -> list[ColumnElement[bool]]:
        posting = models.JobPosting
        found: list[ColumnElement[bool]] = []
        if filter.ids is not None:
            found.append(posting.id.in_(filter.ids))
        if filter.canonical_key is not None:
            found.append(posting.canonical_key == filter.canonical_key)
        if filter.status is not None:
            found.append(posting.status == str(filter.status))
        if filter.has_salary is True:
            found += [posting.salary_min.is_not(None), posting.salary_currency.is_not(None)]
        elif filter.has_salary is False:
            found.append(posting.salary_min.is_(None))
        if filter.missing_embedding_for is not None:
            embedding = models.PostingEmbedding
            found.append(
                ~exists().where(
                    embedding.job_posting_id == posting.id,
                    embedding.model_name == filter.missing_embedding_for,
                )
            )
        return found

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        posting = models.JobPosting
        query = (
            update(posting)
            .where(posting.crawl_source_id == source_id, posting.status == str(PostingStatus.OPEN))
            .values(status=str(PostingStatus.EXPIRED))
        )
        if seen_keys:
            query = query.where(posting.canonical_key.notin_(seen_keys))
        result = await self._session.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)

    async def get_open_in_scope(self, scope: PostingScope) -> list[JobPosting]:
        in_scope = _in_scope(scope)
        if in_scope is None:
            return []  # locations with no words in them, and nothing else chosen
        posting = models.JobPosting
        rows = await self._session.execute(
            select(posting).where(in_scope).order_by(posting.created_at.desc(), posting.id.desc())
        )
        return [mappers.job_posting(row) for row in rows.scalars()]

    async def get_open_heads_in_scope(
        self, scope: PostingScope, posting_ids: tuple[uuid.UUID, ...] | None = None
    ) -> list[PostingHead]:
        in_scope = _in_scope(scope)
        if in_scope is None or posting_ids == ():
            return []
        posting = models.JobPosting
        if posting_ids is not None:
            in_scope = and_(in_scope, posting.id.in_(posting_ids))
        rows = await self._session.execute(
            select(
                posting.id,
                posting.company_id,
                posting.title,
                posting.location,
                posting.url,
                posting.source_kind,
                posting.posted_on,
                posting.salary_min,
                posting.salary_max,
                posting.salary_currency,
                posting.first_seen_at,
            )
            .where(in_scope)
            .order_by(posting.created_at.desc(), posting.id.desc())
        )
        return [mappers.posting_head(row) for row in rows]

    async def thin_unheld(self, *, unseen_since: datetime, at: datetime) -> int:
        posting = models.JobPosting
        unheld = and_(
            posting.thinned_at.is_(None),
            posting.last_seen_at < unseen_since,
            ~and_(posting.status == str(PostingStatus.OPEN), _is_held(posting)),
        )
        thinned = await self._session.execute(
            update(posting)
            .where(unheld)
            .values(description="", thinned_at=at)
            .returning(posting.id)
        )
        ids = [row[0] for row in thinned.all()]
        if ids:
            await self._session.execute(
                delete(models.PostingEmbedding).where(
                    models.PostingEmbedding.job_posting_id.in_(ids)
                )
            )
        return len(ids)


def _in_scope(scope: PostingScope) -> ColumnElement[bool] | None:
    """An open, held posting in this scope; ``None`` when nothing can be."""
    posting = models.JobPosting
    either: list[ColumnElement[bool]] = []
    for market in scope.markets:
        # A country takes in its cities, and a region its member countries
        # (ADR 0026): ``in_market`` in SQL.
        for name in place_names(market):
            if words := market_words(name):
                either.append(_names_every_word(posting.location, words))
    if any(
        target_location_option(market) is not None or search_scope(market) is not None
        for market in scope.markets
    ):
        # Remote work open to anyone is in every listed place, though its
        # location names none of them (ADR 0025).
        either.append(_names_every_word(posting.location, WORLDWIDE_WORDS))
    if scope.includes_baseline:
        either.append(
            posting.crawl_source_id.in_(
                select(models.CrawlSource.id).where(
                    models.CrawlSource.origin == str(SourceOrigin.BASELINE)
                )
            )
        )
    if not either:
        return None
    in_scope = and_(posting.status == str(PostingStatus.OPEN), or_(*either), _is_held(posting))
    if scope.is_bounded:
        # The newest by the day it was posted, else first seen (ADR 0068).
        newest = (
            select(posting.id)
            .where(in_scope)
            .order_by(
                func.coalesce(posting.posted_on, cast(posting.first_seen_at, Date)).desc(),
                posting.created_at.desc(),
                posting.id.desc(),
            )
            .limit(scope.baseline_limit)
        )
        in_scope = posting.id.in_(newest)
    return in_scope


def _is_held(posting: type[models.JobPosting]) -> ColumnElement[bool]:
    """A posting a board found is held while it is open; one a search found
    only while it is on a current result list (ADR 0027)."""
    searches = select(models.CrawlSource.id).where(models.CrawlSource.market.is_not(None))
    listed = exists().where(models.SearchResult.job_posting_id == posting.id)
    return or_(
        posting.crawl_source_id.is_(None),
        posting.crawl_source_id.not_in(searches),
        listed,
    )


def _names_every_word(
    column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    words: tuple[str, ...],
) -> ColumnElement[bool]:
    """``names_every_word`` in SQL: the text, lowercased and folded to ASCII
    the way ``normalize`` folds it, contains each of the words whole. The words
    are ASCII letters and digits, so they are safe in the pattern."""
    folded = func.translate(func.lower(column), *ACCENT_FOLDS)
    return and_(*(folded.regexp_match(rf"\m{word}\M") for word in words))


class SqlAlchemyPostingEmbeddingRepository(
    SqlAlchemyRepository[PostingEmbedding, models.PostingEmbedding, PostingEmbeddingFilter],
    PostingEmbeddingRepository,
):
    model = models.PostingEmbedding
    id_column = models.PostingEmbedding.job_posting_id
    created_column = models.PostingEmbedding.computed_at
    noun = "posting embedding"

    def to_entity(self, row: models.PostingEmbedding) -> PostingEmbedding:
        return mappers.posting_embedding(row)

    def to_row(self, entity: PostingEmbedding) -> models.PostingEmbedding:
        return mappers.posting_embedding_row(entity)

    def apply(self, row: models.PostingEmbedding, entity: PostingEmbedding) -> None:
        mappers.apply_posting_embedding(row, entity)

    def id_of(self, entity: PostingEmbedding) -> uuid.UUID:
        return entity.posting_id

    def conditions(self, filter: PostingEmbeddingFilter) -> list[ColumnElement[bool]]:
        embedding = models.PostingEmbedding
        found: list[ColumnElement[bool]] = []
        if filter.posting_ids is not None:
            found.append(embedding.job_posting_id.in_(filter.posting_ids))
        if filter.model_name is not None:
            found.append(embedding.model_name == filter.model_name)
        return found


class SqlAlchemySearchResultRepository(
    SqlAlchemyRepository[SearchResult, models.SearchResult, SearchResultFilter],
    SearchResultRepository,
):
    model = models.SearchResult
    id_column = models.SearchResult.id
    created_column = models.SearchResult.fetched_at
    noun = "search result"

    def to_entity(self, row: models.SearchResult) -> SearchResult:
        return mappers.search_result(row)

    def to_row(self, entity: SearchResult) -> models.SearchResult:
        return mappers.search_result_row(entity)

    def apply(self, row: models.SearchResult, entity: SearchResult) -> None:
        mappers.apply_search_result(row, entity)

    def id_of(self, entity: SearchResult) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: SearchResultFilter) -> list[ColumnElement[bool]]:
        result = models.SearchResult
        found: list[ColumnElement[bool]] = []
        if filter.crawl_source_ids is not None:
            found.append(result.crawl_source_id.in_(filter.crawl_source_ids))
        if filter.job_posting_ids is not None:
            found.append(result.job_posting_id.in_(filter.job_posting_ids))
        return found

    async def replace(
        self, crawl_source_id: uuid.UUID, posting_ids: list[uuid.UUID], *, at: datetime
    ) -> None:
        result = models.SearchResult
        await self._session.execute(delete(result).where(result.crawl_source_id == crawl_source_id))
        listed = list(dict.fromkeys(posting_ids))
        if listed:
            await self._session.execute(
                insert(result),
                [
                    {
                        "id": uuid.uuid4(),
                        "crawl_source_id": crawl_source_id,
                        "job_posting_id": posting_id,
                        "rank": rank,
                        "fetched_at": at,
                    }
                    for rank, posting_id in enumerate(listed)
                ],
            )


# --- owner zone ------------------------------------------------------------


class SqlAlchemyMarketPreferenceRepository(
    SqlAlchemyRepository[MarketPreference, models.MarketPreference, MarketPreferenceFilter],
    MarketPreferenceRepository,
):
    model = models.MarketPreference
    id_column = models.MarketPreference.id
    created_column = models.MarketPreference.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.MarketPreference.owner_id
    )
    noun = "market preference"

    def to_entity(self, row: models.MarketPreference) -> MarketPreference:
        return mappers.market_preference(row)

    def to_row(self, entity: MarketPreference) -> models.MarketPreference:
        return mappers.market_preference_row(entity)

    def apply(self, row: models.MarketPreference, entity: MarketPreference) -> None:
        mappers.apply_market_preference(row, entity)

    def id_of(self, entity: MarketPreference) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: MarketPreferenceFilter) -> list[ColumnElement[bool]]:
        preference = models.MarketPreference
        found: list[ColumnElement[bool]] = []
        if filter.market is not None:
            found.append(preference.market == filter.market)
        return found
