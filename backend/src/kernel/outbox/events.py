"""Event names, in one place.

These are the events from docs/domain_model.md section 3 that Phase 1
actually emits. A name is a contract between modules, so it is spelled once
here rather than typed as a string at each call site.
"""

from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    # Profile
    SOURCE_SYNCED = "SourceSynced"
    PROFILE_UPDATED = "ProfileUpdated"
    # Assessment
    ASSESSMENT_REQUESTED = "AssessmentRequested"
    ASSESSMENT_COMPLETED = "AssessmentCompleted"
    ANALYSIS_FINISHED = "AnalysisFinished"
    QUESTIONS_RAISED = "QuestionsRaised"
    QUESTION_ANSWERED = "QuestionAnswered"
    DIMENSIONS_CHANGED = "DimensionsChanged"
    ROLE_FITS_COMPUTED = "RoleFitsComputed"
    # Market / crawler
    TARGET_LOCATIONS_CHANGED = "TargetLocationsChanged"
    CRAWL_COMPLETED = "CrawlCompleted"
    POSTINGS_CHANGED = "PostingsChanged"
    POSTINGS_EXPIRED = "PostingsExpired"
    # Role map
    ROLES_RECLUSTERED = "RolesReclustered"
    CUSTOM_ROLE_ADDED = "CustomRoleAdded"
    ROLE_REQUIREMENTS_CHANGED = "RoleRequirementsChanged"
    ROLE_SPLIT_OR_MERGED = "RoleSplitOrMerged"
    # Gap plan
    PLAN_DRAFTED = "PlanDrafted"
    # Résumé
    RESUME_TAILORED = "ResumeTailored"
    RESUME_VERSION_SAVED = "ResumeVersionSaved"
    # Identity / AI
    ANALYSIS_COST_ESTIMATED = "AnalysisCostEstimated"
    ANALYSIS_COST_CONFIRMED = "AnalysisCostConfirmed"
    PROVIDER_CREDENTIAL_FAILED = "ProviderCredentialFailed"
    USAGE_BUDGET_EXCEEDED = "UsageBudgetExceeded"
    BACKGROUND_JOBS_PAUSED = "BackgroundJobsPaused"
