"""ORM rows to market entities and back. No rules live here, only shape."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row

from advisor.market.domain import (
    Company,
    CrawlSource,
    JobPosting,
    MarketPreference,
    PostingEmbedding,
    PostingHead,
    PostingStatus,
    SalaryRange,
    SearchResult,
    SourceOrigin,
    SourceStatus,
)
from advisor.market.infra import models

# --- company ---------------------------------------------------------------


def company(row: models.Company) -> Company:
    return Company(
        id=row.id,
        name=row.name,
        normalized_name=row.normalized_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def company_row(entity: Company) -> models.Company:
    row = models.Company(id=entity.id)
    apply_company(row, entity)
    return row


def apply_company(row: models.Company, entity: Company) -> None:
    row.name = entity.name
    row.normalized_name = entity.normalized_name


def company_values(entity: Company) -> dict[str, Any]:
    """A company as one row of a bulk insert."""
    return {"id": entity.id, "name": entity.name, "normalized_name": entity.normalized_name}


# --- crawl source ----------------------------------------------------------


def crawl_source(row: models.CrawlSource) -> CrawlSource:
    return CrawlSource(
        id=row.id,
        kind=row.kind,
        endpoint=row.endpoint,
        company_id=row.company_id,
        market=row.market,
        origin=SourceOrigin(row.origin),
        status=SourceStatus(row.status),
        last_fetched_at=row.last_fetched_at,
        last_error=row.last_error,
        last_requested_at=row.last_requested_at,
        due_at=row.due_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def crawl_source_row(entity: CrawlSource) -> models.CrawlSource:
    row = models.CrawlSource(id=entity.id)
    apply_crawl_source(row, entity)
    return row


def apply_crawl_source(row: models.CrawlSource, entity: CrawlSource) -> None:
    row.kind = entity.kind
    row.endpoint = entity.endpoint
    row.company_id = entity.company_id
    row.market = entity.market
    row.origin = str(entity.origin)
    row.status = str(entity.status)
    row.last_fetched_at = entity.last_fetched_at
    row.last_error = entity.last_error
    row.last_requested_at = entity.last_requested_at
    row.due_at = entity.due_at


# --- job posting -----------------------------------------------------------


def salary(row: models.JobPosting | Row[Any]) -> SalaryRange | None:
    if row.salary_min is None:
        return None
    return SalaryRange(
        min_amount=row.salary_min,
        max_amount=row.salary_max or row.salary_min,
        currency=row.salary_currency or "",
    )


def job_posting(row: models.JobPosting) -> JobPosting:
    return JobPosting(
        id=row.id,
        canonical_key=row.canonical_key,
        company_id=row.company_id,
        crawl_source_id=row.crawl_source_id,
        title=row.title,
        location=row.location,
        description=row.description,
        url=row.url,
        source_kind=row.source_kind,
        posted_on=row.posted_on,
        salary=salary(row),
        status=PostingStatus(row.status),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        thinned_at=row.thinned_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def posting_head(row: Row[Any]) -> PostingHead:
    """A posting read without its description (``get_open_heads_in_scope``)."""
    return PostingHead(
        id=row.id,
        company_id=row.company_id,
        title=row.title,
        location=row.location,
        url=row.url,
        source_kind=row.source_kind,
        posted_on=row.posted_on,
        salary=salary(row),
        first_seen_at=row.first_seen_at,
    )


def job_posting_row(entity: JobPosting) -> models.JobPosting:
    row = models.JobPosting(id=entity.id, first_seen_at=entity.first_seen_at)
    apply_job_posting(row, entity)
    return row


def apply_job_posting(row: models.JobPosting, entity: JobPosting) -> None:
    row.canonical_key = entity.canonical_key
    row.company_id = entity.company_id
    row.crawl_source_id = entity.crawl_source_id
    row.title = entity.title
    row.location = entity.location
    row.description = entity.description
    row.url = entity.url
    row.source_kind = entity.source_kind
    row.posted_on = entity.posted_on
    row.status = str(entity.status)
    row.last_seen_at = entity.last_seen_at
    row.thinned_at = entity.thinned_at
    if entity.salary is not None:
        row.salary_min = entity.salary.min_amount
        row.salary_max = entity.salary.max_amount
        row.salary_currency = entity.salary.currency


def job_posting_values(entity: JobPosting) -> dict[str, Any]:
    """A posting as one row of a bulk insert or update. Every posting gives
    the same keys, so a batch is one statement."""
    salary = entity.salary
    return {
        "id": entity.id,
        "canonical_key": entity.canonical_key,
        "company_id": entity.company_id,
        "crawl_source_id": entity.crawl_source_id,
        "title": entity.title,
        "location": entity.location,
        "description": entity.description,
        "url": entity.url,
        "source_kind": entity.source_kind,
        "posted_on": entity.posted_on,
        "salary_min": salary.min_amount if salary is not None else None,
        "salary_max": salary.max_amount if salary is not None else None,
        "salary_currency": salary.currency if salary is not None else None,
        "status": str(entity.status),
        "first_seen_at": entity.first_seen_at,
        "last_seen_at": entity.last_seen_at,
        "thinned_at": entity.thinned_at,
    }


def search_result(row: models.SearchResult) -> SearchResult:
    return SearchResult(
        id=row.id,
        crawl_source_id=row.crawl_source_id,
        job_posting_id=row.job_posting_id,
        rank=row.rank,
        fetched_at=row.fetched_at,
    )


def search_result_row(entity: SearchResult) -> models.SearchResult:
    row = models.SearchResult(id=entity.id)
    apply_search_result(row, entity)
    return row


def apply_search_result(row: models.SearchResult, entity: SearchResult) -> None:
    row.crawl_source_id = entity.crawl_source_id
    row.job_posting_id = entity.job_posting_id
    row.rank = entity.rank
    row.fetched_at = entity.fetched_at


# --- owner zone ------------------------------------------------------------


def market_preference(row: models.MarketPreference) -> MarketPreference:
    return MarketPreference(
        id=row.id,
        owner_id=row.owner_id,
        market=row.market,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def market_preference_row(entity: MarketPreference) -> models.MarketPreference:
    return models.MarketPreference(id=entity.id, owner_id=entity.owner_id, market=entity.market)


def apply_market_preference(row: models.MarketPreference, entity: MarketPreference) -> None:
    row.market = entity.market


def posting_embedding(row: models.PostingEmbedding) -> PostingEmbedding:
    return PostingEmbedding(
        posting_id=row.job_posting_id,
        model_name=row.model_name,
        vector=list(row.vector),
        computed_at=row.computed_at,
    )


def posting_embedding_row(entity: PostingEmbedding) -> models.PostingEmbedding:
    return models.PostingEmbedding(
        job_posting_id=entity.posting_id, model_name=entity.model_name, vector=entity.vector
    )


def posting_embedding_values(entity: PostingEmbedding) -> dict[str, Any]:
    """An embedding as one row of a bulk insert."""
    return {
        "job_posting_id": entity.posting_id,
        "model_name": entity.model_name,
        "vector": entity.vector,
    }


def apply_posting_embedding(row: models.PostingEmbedding, entity: PostingEmbedding) -> None:
    row.model_name = entity.model_name
    row.vector = entity.vector
