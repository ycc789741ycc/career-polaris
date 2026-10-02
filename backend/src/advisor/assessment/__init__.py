"""The assessment component.

The strength report: the user's skill dimensions and their scores.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``assessment-public-surface``).
"""

from advisor.assessment import jobs
from advisor.assessment.factory import create_assessment_service
from advisor.assessment.service import (
    AnalysisRunView,
    AssessmentService,
    AssessmentView,
    DimensionView,
)

__all__ = [
    "AnalysisRunView",
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
    "create_assessment_service",
    "jobs",
]
