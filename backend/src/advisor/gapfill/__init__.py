"""The gapfill component.

Fill the gap, the Advisor's first step (domain decision 27, ADR 0023):
questions per gap of one Target, and the one submit that records every answer
as ``user_answer`` evidence.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``gapfill-public-surface``).
"""

from advisor.gapfill import jobs
from advisor.gapfill.factory import create_gapfill_service
from advisor.gapfill.service import (
    Answer,
    GapFillService,
    GapView,
    QuestionSetView,
    QuestionView,
    SubmittedView,
)

__all__ = [
    "Answer",
    "GapFillService",
    "GapView",
    "QuestionSetView",
    "QuestionView",
    "SubmittedView",
    "create_gapfill_service",
    "jobs",
]
