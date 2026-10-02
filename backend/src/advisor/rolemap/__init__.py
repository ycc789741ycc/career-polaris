"""The rolemap component.

The roles the user's strengths point to, found on the market: the user's role map.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``rolemap-public-surface``).
"""

from advisor.rolemap import jobs
from advisor.rolemap.domain import (
    CANDIDATE_ROLE_COUNT,
    DEFAULT_MATCHES,
    MAX_COMPANY_NAME,
    MAX_MATCHES,
    MAX_ROLE_REQUIREMENTS,
    MAX_ROLE_TITLE,
    MAX_STRENGTHS,
    MIN_MATCHES,
    RECOMMENDED_ROLE_COUNT,
)
from advisor.rolemap.factory import create_rolemap_service
from advisor.rolemap.service import (
    BuildRequestView,
    BuildRunView,
    CandidateInput,
    FitView,
    MarketWait,
    MatchedPostingView,
    RequirementView,
    RoleCandidateView,
    RoleMapService,
    RoleView,
    StrengthInput,
)

__all__ = [
    "CANDIDATE_ROLE_COUNT",
    "DEFAULT_MATCHES",
    "MAX_COMPANY_NAME",
    "MAX_MATCHES",
    "MAX_ROLE_REQUIREMENTS",
    "MAX_ROLE_TITLE",
    "MAX_STRENGTHS",
    "MIN_MATCHES",
    "RECOMMENDED_ROLE_COUNT",
    "BuildRequestView",
    "BuildRunView",
    "CandidateInput",
    "FitView",
    "MarketWait",
    "MatchedPostingView",
    "RequirementView",
    "RoleCandidateView",
    "RoleMapService",
    "RoleView",
    "StrengthInput",
    "create_rolemap_service",
    "jobs",
]
