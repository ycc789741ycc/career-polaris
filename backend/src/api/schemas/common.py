"""Shapes more than one component's HTTP surface uses.

Every request and response body in ``api/schemas`` derives from ``ApiModel``.
Responses are built from a component's views (``advisor.<c>``), never from its
entities: the view is the component's contract, the schema is the wire's
(ADR 0013).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

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
    "RequestModel",
    "Salary",
    "TargetEstimate",
    "Timestamp",
]
