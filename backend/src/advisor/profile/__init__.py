"""The profile component.

The CareerProfile: career timeline and evidence from connectors and uploaded
résumés.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``profile-public-surface``).
"""

from advisor.profile import jobs
from advisor.profile.factory import create_profile_service
from advisor.profile.infra.connectors import (
    GitHubConnector,
    JiraConnector,
)
from advisor.profile.infra.connectors.github import (
    SCOPE_DESCRIPTIONS as GITHUB_SCOPE_DESCRIPTIONS,
)
from advisor.profile.infra.connectors.jira import (
    SCOPE_DESCRIPTIONS as JIRA_SCOPE_DESCRIPTIONS,
)
from advisor.profile.infra.oauth import (
    authorize_url,
    exchange_code,
    sign_state,
    verify_state,
)
from advisor.profile.service import (
    ACCEPTED_TYPES,
    AnswerRecord,
    CitationError,
    CitationHandles,
    ConnectionView,
    EvidenceSource,
    EvidenceView,
    PendingSourceView,
    PositionReading,
    ProfileService,
    ProfileSnapshot,
    ResumeFileView,
    SourceProcessingView,
    TimelineError,
    assert_citations_exist,
    assert_position_readings_valid,
    get_evidence_line,
)

__all__ = [
    "ACCEPTED_TYPES",
    "GITHUB_SCOPE_DESCRIPTIONS",
    "JIRA_SCOPE_DESCRIPTIONS",
    "AnswerRecord",
    "CitationError",
    "CitationHandles",
    "ConnectionView",
    "EvidenceSource",
    "EvidenceView",
    "GitHubConnector",
    "JiraConnector",
    "PendingSourceView",
    "PositionReading",
    "ProfileService",
    "ProfileSnapshot",
    "ResumeFileView",
    "SourceProcessingView",
    "TimelineError",
    "assert_citations_exist",
    "assert_position_readings_valid",
    "authorize_url",
    "create_profile_service",
    "exchange_code",
    "get_evidence_line",
    "jobs",
    "sign_state",
    "verify_state",
]
