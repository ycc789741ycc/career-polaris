"""The resume component.

Résumés tailored to a Target, their versions, revisions and PDF exports.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``resume-public-surface``).
"""

from advisor.resume import jobs
from advisor.resume.factory import create_resume_service
from advisor.resume.service import (
    CoverageView,
    ExportView,
    Options,
    ResumeService,
    ResumeSummaryView,
    ResumeView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    RevisionView,
    SectionKind,
    SectionSlot,
    Template,
    TemplateView,
    VersionView,
)

__all__ = [
    "CoverageView",
    "ExportView",
    "Options",
    "ResumeService",
    "ResumeSummaryView",
    "ResumeView",
    "RevisionDone",
    "RevisionFailed",
    "RevisionText",
    "RevisionView",
    "SectionKind",
    "SectionSlot",
    "Template",
    "TemplateView",
    "VersionView",
    "create_resume_service",
    "jobs",
]
