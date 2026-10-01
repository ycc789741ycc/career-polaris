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
    MAX_COMPANY_NAME,
    MAX_ROLE_REQUIREMENTS,
    MAX_ROLE_TITLE,
    RECOMMENDED_ROLE_COUNT,
)
from advisor.rolemap.factory import create_rolemap_service
from advisor.rolemap.service import (
    BuildRequestView,
    BuildRunView,
    CandidateInput,
    RequirementView,
    RoleCandidateView,
    RoleMapService,
    RoleView,
)

__all__ = [
    "CANDIDATE_ROLE_COUNT",
    "MAX_COMPANY_NAME",
    "MAX_ROLE_REQUIREMENTS",
    "MAX_ROLE_TITLE",
    "RECOMMENDED_ROLE_COUNT",
    "BuildRequestView",
    "BuildRunView",
    "CandidateInput",
    "RequirementView",
    "RoleCandidateView",
    "RoleMapService",
    "RoleView",
    "create_rolemap_service",
    "jobs",
]
