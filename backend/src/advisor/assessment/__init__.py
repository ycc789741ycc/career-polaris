"""The assessment component.

The strength report: skill dimensions, role fits and follow-up questions.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``assessment-public-surface``).
"""

from advisor.assessment import jobs
from advisor.assessment.domain import (
    DEFAULT_MATCHES,
    MAX_MATCHES,
    MIN_MATCHES,
    QuestionRoundTrigger,
)
from advisor.assessment.factory import create_assessment_service
from advisor.assessment.service import (
    AnalysisRunView,
    AssessmentService,
    AssessmentView,
    DimensionView,
    FitView,
    MatchedPostingView,
    QuestionRoundView,
    QuestionView,
)

__all__ = [
    "DEFAULT_MATCHES",
    "MAX_MATCHES",
    "MIN_MATCHES",
    "AnalysisRunView",
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
    "FitView",
    "MatchedPostingView",
    "QuestionRoundTrigger",
    "QuestionRoundView",
    "QuestionView",
    "create_assessment_service",
    "jobs",
]
