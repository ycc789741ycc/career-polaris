"""The target component.

Resolves what a plan or résumé aims at, and keeps the postings of the user's
own that one can aim at instead of a role (ADR 0005, ADR 0033).

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``target-public-surface``).
"""

from advisor.target import jobs
from advisor.target.domain import (
    MAX_COMPANY_NAME,
    MAX_JOB_DESCRIPTION,
    MAX_REQUIREMENT_LINE,
    MAX_REQUIREMENT_LINES,
    MAX_TITLE,
    gap_key_for_dimension,
    gap_key_for_uncovered,
)
from advisor.target.factory import create_target_service
from advisor.target.service import (
    DimensionGap,
    DraftBasis,
    OutdatedReason,
    OwnPostingView,
    TargetError,
    TargetPreview,
    TargetRef,
    TargetService,
    TargetSnapshot,
    UncoveredGap,
    get_target_digest,
    requirements_block,
)

__all__ = [
    "MAX_COMPANY_NAME",
    "MAX_JOB_DESCRIPTION",
    "MAX_REQUIREMENT_LINE",
    "MAX_REQUIREMENT_LINES",
    "MAX_TITLE",
    "DimensionGap",
    "DraftBasis",
    "OutdatedReason",
    "OwnPostingView",
    "TargetError",
    "TargetPreview",
    "TargetRef",
    "TargetService",
    "TargetSnapshot",
    "UncoveredGap",
    "create_target_service",
    "gap_key_for_dimension",
    "gap_key_for_uncovered",
    "get_target_digest",
    "jobs",
    "requirements_block",
]
