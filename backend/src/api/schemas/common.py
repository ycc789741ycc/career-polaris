"""Shapes more than one component's HTTP surface uses.

Every request and response body in ``api/schemas`` derives from ``ApiModel``.
Responses are built from a component's views (``advisor.<c>``), never from its
entities: the view is the component's contract, the schema is the wire's
(ADR 0013).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, PlainSerializer

from advisor.market import SalaryRange


class ApiModel(BaseModel):
    """A response: frozen, and no field the schema does not name."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RequestModel(BaseModel):
    """A request body. Unknown fields are ignored, as they always have been, so
    an older client sending one more field is not refused."""

    model_config = ConfigDict(frozen=True)


# ``isoformat()`` rather than Pydantic's default, which writes UTC as ``Z``: the
# wire has always carried ``+00:00``, and a contract change should be a choice.
Timestamp = Annotated[datetime, PlainSerializer(lambda d: d.isoformat(), return_type=str)]


class PageOf[V](Protocol):
    """What a list use case hands back (``kernel.paging.Page``), read-only.

    Named structurally so this module stays free of the kernel.
    """

    @property
    def items(self) -> Sequence[V]: ...
    @property
    def page(self) -> int: ...
    @property
    def page_size(self) -> int | None: ...
    @property
    def total(self) -> int: ...


class Page[ItemT](ApiModel):
    """Every list endpoint's body: one page and the size of the whole (ADR 0014).

    Each list declares a named subclass (``class RolePage(Page[Role])``), which is
    the name the OpenAPI document and the client see.
    """

    items: list[ItemT]
    # 1-based.
    page: int
    # Null when the client asked for the whole list.
    page_size: int | None
    # Every item the list holds, not just this page's.
    total: int

    @classmethod
    def of[V](cls, page: PageOf[V], convert: Callable[[V], ItemT]) -> Self:
        return cls(
            items=[convert(item) for item in page.items],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )


class StringPage(Page[str]):
    pass


class Accepted(ApiModel):
    """A 202: the work is queued, and something else reports how it went."""

    status: Literal["queued"] = "queued"


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorEnvelope(ApiModel):
    """Every non-2xx body (``api.errors``): a stable code and a readable message."""

    error: ErrorDetail


# Declared on every router, so the generated client knows what a failure carries.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorEnvelope, "description": "The request could not be read."},
    "4XX": {"model": ErrorEnvelope, "description": "Refused, with a stable code."},
    "5XX": {"model": ErrorEnvelope, "description": "Failed, with a stable code."},
}


class JobError(ApiModel):
    """Why a drafting, rendering or generating job failed, by stable code."""

    code: str
    message: str | None

    @classmethod
    def of(cls, code: str | None, message: str | None) -> JobError | None:
        return cls(code=code, message=message) if code else None


class Salary(ApiModel):
    min: int
    max: int
    currency: str

    @classmethod
    def of(cls, salary: SalaryRange | None) -> Salary | None:
        if salary is None:
            return None
        return cls(min=salary.min_amount, max=salary.max_amount, currency=salary.currency)


class EvidenceCitation(ApiModel):
    """One cited piece of Evidence, by the handle the AI used for it."""

    id: str
    reference: str
    fact: str


class CostEstimate(ApiModel):
    """What an AI run will cost on the user's key, shown before it runs."""

    # A decimal string: money never goes through a float.
    cost_usd: str
    model_id: str | None
    input_tokens: int
    # False when the model's price is a guess, which the page says plainly.
    rate_is_published: bool


class AnalysisEstimate(CostEstimate):
    """The price of Analyze: the analysis and the role-map build that follows
    it, confirmed once (domain decision 24). ``cost_usd`` is their sum."""

    analysis_cost_usd: str
    # A ceiling: the ten recommended roles at most, fewer on a thin market.
    role_map_cost_usd: str
    max_roles: int


class TargetEstimate(CostEstimate):
    """The price of drafting for a Target: a gap plan or a tailored résumé."""

    # A pasted JD still has to be read and scored; that is included.
    includes_scoring: bool


__all__ = [
    "ERROR_RESPONSES",
    "Accepted",
    "ApiModel",
    "CostEstimate",
    "ErrorDetail",
    "ErrorEnvelope",
    "EvidenceCitation",
    "JobError",
    "Page",
    "PageOf",
    "RequestModel",
    "Salary",
    "StringPage",
    "TargetEstimate",
    "Timestamp",
]
