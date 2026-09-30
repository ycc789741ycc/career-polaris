"""Himalayas, a public API of remote jobs searched by title and place.

``https://himalayas.app/jobs/api/search?q=<title>&country=<ISO code>``

Free and keyless, so the crawler still holds no secret (ADR 0025). Its terms
ask that every job links back to its Himalayas URL and names Himalayas as the
source, which is why the posting's link is that URL and never the employer's.

Only the first page of a search is read. The site's robots.txt disallows
``/jobs*&page=``, and the twenty most relevant openings are enough to tell
whether a place has a role.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from advisor.market.crawling.adapters.base import (
    PostingSource,
    parse_date,
    salary_from,
    strip_html,
)
from advisor.market.service import (
    NormalizedPosting,
    SalaryRange,
    SearchScope,
    SourceKind,
    normalize_title,
    remote_location,
    salary_in_text,
)

BASE = "https://himalayas.app/jobs/api/search"


class HimalayasAdapter(PostingSource):
    name = "himalayas"
    source_kind = SourceKind.PUBLIC_API

    def search_endpoint(self, title: str, scope: SearchScope) -> str | None:
        """The search for one job title in one place, or ``None`` when the
        title has no words to search for.

        Only the title is sent, folded to plain lowercase words, so the same
        title from two analyses is the same endpoint and one shared source.
        """
        words = normalize_title(title)
        if not words:
            return None
        place = (
            ("worldwide", "true") if scope.country_code is None else ("country", scope.country_code)
        )
        return f"{BASE}?{urlencode([('q', words), place], quote_via=quote)}"

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]:
        jobs = (payload or {}).get("jobs") if isinstance(payload, dict) else None
        postings: list[NormalizedPosting] = []
        for job in jobs or []:
            title = str(job.get("title") or "").strip()
            company = str(job.get("companyName") or "").strip()
            link = str(job.get("guid") or job.get("applicationLink") or "").strip()
            if not title or not company or not link:
                continue
            description = strip_html(job.get("description") or job.get("excerpt") or "")
            postings.append(
                NormalizedPosting(
                    external_id=link,
                    company_name=company,
                    title=title,
                    location=remote_location(_names(job.get("locationRestrictions"))),
                    description=description,
                    url=link,
                    source_kind=self.source_kind,
                    posted_on=parse_date(job.get("pubDate")),
                    salary=_annual_salary(job) or salary_in_text(description),
                )
            )
        return postings


def _names(restrictions: Any) -> list[str]:
    if not isinstance(restrictions, list):
        return []
    return [str(name) for name in restrictions if isinstance(name, str)]


def _annual_salary(job: dict[str, Any]) -> SalaryRange | None:
    """The published range, when it is a yearly one: the salary bands compare
    yearly pay, and an hourly rate read as a salary would skew them."""
    if str(job.get("salaryPeriod") or "").lower() != "annual":
        return None
    return salary_from(job.get("minSalary"), job.get("maxSalary"), job.get("currency"))
