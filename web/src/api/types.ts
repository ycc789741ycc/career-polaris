/**
 * Response shapes, named for the call sites that use them.
 *
 * Every type here is an alias over `schema.d.ts`, which `make gen-client`
 * generates from the API's OpenAPI document, and CI fails if it drifts. So a
 * field the API renames or drops fails `make typecheck` here rather than
 * reaching a screen as `undefined` (ADR 0013). Nothing in this file restates a
 * field: to change a shape, change its schema in `backend/src/api/schemas/`
 * and run `make gen-client`.
 */

import type { components } from "./schema";

type Schemas = components["schemas"];

// Activity
/** What background work is running, which the shell polls (ADR 0018). */
export type Activity = Schemas["Activity"];
/** The newest analysis or role-map build. */
export type RunStatus = Schemas["RunStatus"];
export type PendingWork = Schemas["PendingWork"];

// Identity
export type Me = Schemas["Me"];
export type Credential = Schemas["Credential"];
export type Budget = Schemas["Budget"];

// Profile
export type Connection = Schemas["Connection"];
export type ResumeFile = Schemas["ResumeFile"];
export type Evidence = Schemas["Evidence"];
/** The profile's headline numbers and timeline (`GET /profile`). */
export type ProfileSummary = Schemas["Profile"];

// Assessment
export type Dimension = Schemas["Dimension"];
export type Assessment = Schemas["Assessment"];
export type Fit = Schemas["Fit"];
/** An opening inside one of the user's roles, ranked by that role's fit. */
export type MatchedPosting = Schemas["MatchedPosting"];
/** Analyze: the analysis and the role-map build after it, confirmed once (ADR 0020). */
export type AnalysisEstimate = Schemas["AnalysisEstimate"];

// Role map
export type SalaryBand = Schemas["SalaryBand"];
export type Role = Schemas["Role"];
/** A role the latest analysis recommended, and the role it became (ADR 0024). */
export type RoleCandidate = Schemas["RoleCandidate"];
/** A posting the user brings themselves, to aim the Advisor at (Phase 8). */
export type OwnPosting = Schemas["OwnPosting"];
/** What reading and scoring a posting of the user's own costs, first. */
export type OwnPostingEstimate = Schemas["OwnPostingEstimate"];
/** The most a role-map rebuild can cost, fits included: a ceiling at the
 * top k roles a build keeps, `max_roles` (ADR 0024, ADR 0029). */
export type RoleMapEstimate = Schemas["RoleMapEstimate"];

// Market
/** The user's target locations and the open postings they take in (domain decision 21). */
export type MarketScope = Schemas["MarketScope"];

// Targets: a role, and optionally one opening in it (ADR 0022)
export type TargetRef = Schemas["TargetRefBody"];

// Fill the gap (ADR 0023)
/** The questions for one Target's gaps; polled while `writing`. */
export type QuestionSet = Schemas["QuestionSet"];
export type GapQuestion = Schemas["GapQuestion"];
/** What submitting costs: the plan and résumé written again, if they exist. */
export type SubmitEstimate = Schemas["SubmitEstimate"];
export type Submitted = Schemas["Submitted"];

// Gap plan
export type PlanSummary = Schemas["PlanSummary"];
export type PlanStatus = PlanSummary["status"];
export type PlanGap = Schemas["PlanGap"];
export type PlanTask = Schemas["PlanTask"];
export type Plan = Schemas["Plan"];
/** What drafting for a Target costs. */
export type PlanEstimate = Schemas["TargetEstimate"];

// Tailored résumé
export type ResumeTemplate = Schemas["TailoredResume"]["template"];
export type ResumeOptions = Schemas["ResumeOptions"];
export type ResumeBullet = Schemas["ResumeBullet"];
export type ResumeContent = Schemas["ResumeContent"];
export type ResumeSummary = Schemas["ResumeSummary"];
export type ResumeVersion = Schemas["ResumeVersion"];
export type TailoredResume = Schemas["TailoredResume"];
export type ResumeExport = Schemas["ResumeExport"];

// Pages: every list endpoint answers with one (ADR 0014). `api.items<P>` unwraps it.
export type AssessmentPage = Schemas["AssessmentPage"];
export type ConnectionPage = Schemas["ConnectionPage"];
export type EvidencePage = Schemas["EvidencePage"];
export type FitPage = Schemas["FitPage"];
export type MatchedPostingPage = Schemas["MatchedPostingPage"];
export type OwnPostingPage = Schemas["OwnPostingPage"];
export type PlanSummaryPage = Schemas["PlanSummaryPage"];
export type ResumeFilePage = Schemas["ResumeFilePage"];
export type ResumeSummaryPage = Schemas["ResumeSummaryPage"];
export type RoleCandidatePage = Schemas["RoleCandidatePage"];
export type RolePage = Schemas["RolePage"];
export type RoleMapState = Schemas["RoleMapState"];
export type StringPage = Schemas["StringPage"];
export type TargetLocationOption = Schemas["TargetLocationOption"];
export type TargetLocationOptionPage = Schemas["TargetLocationOptionPage"];
