# 0028. Score the fit in the role map, against the scores the analysis hands over

**Status:** Accepted — 2026-10-03. Amends [0018](0018-gate-journey-stages-on-recorded-run-status.md) and [0024](0024-recommend-roles-from-the-assessment-and-keep-the-ten-the-market-has.md). Amended by [0032](0032-work-out-every-openings-fit-locally-from-its-roles.md).

## Context

A fit compares one user with one role. It says:

- how far the user's score on each dimension falls short of what the role
  wants (the gaps);
- which of the role's requirements the user has no evidence for at all (the
  uncovered requirements);
- what closing each gap is worth;
- and, from all of that, the bubble's size and the rank of the openings inside
  each role.

All of this lived in `assessment`: the `RoleFit` snapshot, `compute_fits`,
the `fit_projection` call, the arithmetic in `domain/fit.py`, and the ranking
of matched openings. So `assessment` described two things:

- **the user:** the strength report, which the journey's 02 Strengths shows;
- **the user against each role:** what 03 Role map shows.

The journey runs forward, and the strength report shows no fit, role or bar
(`CLAUDE.md`). Yet the component behind it owned everything the role map's
bubbles are sized by. And the one input a fit needs from the user, their
dimensions with score and confidence, `assessment` already hands to `rolemap`
with the candidate roles, for the local fit estimate (ADR 0027).

ADR 0018 put `assessment` above `rolemap` in the import layers "because fit
reads the roles". That stays true of the order, for a different reason:
`assessment` hands the candidates and their scores down.

## Decision

The fit is the role map's.

- **What moves to `rolemap`:**
  - The `RoleFit` entity and repository, and its table: `assessment.role_fit`
    becomes `rolemap.role_fit`, owner-zone under row-level security.
    Migration 0023 moves the rows.
  - The fit arithmetic (`evaluate`, gaps, `closing_lifts`), the ranking of
    matched openings (`rank_matches`), and the rank correlation that checks
    the local estimate (`spearman`).
  - The `fit_projection` call, ledgered as `rolemap.fit`; and
    `RoleFitsComputed`.
  - `FitView` and `MatchedPostingView`.
  - `compute_fits`, `fits`, `matched_postings` and `estimate_fits` on
    `RoleMapService`.
- **The user's side is handed down, not read up.**
  - `StrengthInput` and `rolemap.candidate_strength` carry each dimension's
    `score` and `confidence`, beside the name, read and weight (now derived
    as score × confidence).
  - A fit is projected against those, and records the `assessment_id` they
    came from.
  - `rolemap` still imports nothing from `assessment`.
  - At most `MAX_STRENGTHS` (10) dimensions are handed over, which is what a
    fit is priced for.
- **Scoring is a `rolemap` job.**
  - `RoleMapBuildFinished` queues `rolemap.compute_fits` on the `ai` queue,
    once per build, as before (ADR 0024).
  - It stays separate from the build job, so a failure while scoring neither
    fails nor repeats role analysis the user has paid for.
- **Callers ask `rolemap`.**
  - `target` freezes a Target with the role's fit from `rolemap`, and
    `gapplan` ranks gaps by it.
  - `/fits`, `/fits/compute` and `/matched-postings` are served by the role
    map's router, at the same paths.
  - The fit's body drops `private_posting_id`, which nothing has set since
    ADR 0022, and its `role_id` is never null.
- **What `assessment` keeps:** analysis runs, dimensions and their scores,
  lineage, the candidates it hands over, and the strength report.
- **The migration.**
  - **Strengths:** a strength handed over before this takes its score and
    confidence from the analysis that produced it. A user whose latest
    analysis predates the hand-over gets their strengths from that analysis,
    so their fits can still be scored without analysing again.
  - **Fits:** fits without a role (pasted JDs scored before ADR 0022) are not
    carried over.

## Consequences

Easier:

- One component owns everything 03 Role map shows: the roles, their openings,
  their bars and their fits. `assessment` describes only the user, as 02
  Strengths does.
- Scoring a fit needs no call into `assessment`: the scores it reads are
  already beside the candidates, and in step with them.
- The Spearman check of the local estimate reads candidates and fits in one
  component.

Harder:

- `rolemap` keeps a second copy of the user's latest scores, with confidence,
  replaced on every analysis. If the hand-over and the stored assessment
  drift, the fits silently use the hand-over. Both are written by the same
  `assessment.run`, one after the other.
- A fit can only be scored after a successful analysis has handed its scores
  over. A user with an analysis older than the hand-over depends on the
  migration's backfill.
- Ledger rows keep their task name. Fits scored before this read
  `assessment.fit`, and later ones `rolemap.fit`, so usage by task splits at
  the change.
- `rolemap` grows again: building, choosing, analysing and now scoring live
  in one service.
- Migration 0023 copies every user's fits and drops the old table. Its
  downgrade copies them back, but not the pasted-JD fits it left behind.

## Alternatives considered

- **Leave the fit in `assessment`.** It works, and import-linter is satisfied.
  It lost because it keeps `assessment` owning what only the role map shows,
  and because the scores a fit needs were already being handed to `rolemap`.
- **Have `rolemap` read the latest scores from `assessment`.** That would
  invert the layers (ADR 0018) or need a new port, so `rolemap` would depend
  on the component that depends on it. Handing the scores down is how the
  candidates already travel.
- **Score the fits inside the build job.** One job instead of two. It lost
  because a failed fit projection would fail a build whose roles were already
  analysed on the user's key, and a retry would pay for that analysis again.
- **A new `fit` component between them.** It would hold only the fit, and
  still need the roles from `rolemap` and the scores from `assessment`, adding
  a layer for a few hundred lines.
