# 0031. Keep a role candidate as a query, and record what a build made of it on the build

**Status:** Accepted — 2026-10-04. Amends [0024](0024-recommend-roles-from-the-assessment-and-keep-the-ten-the-market-has.md) and [0027](0027-fetch-the-market-only-when-a-build-needs-it.md).

## Context

ADR 0024 made a `RoleCandidate` the role an analysis recommends, and ADR 0027
had each build write back onto it what it made of it: `role_id`,
`opening_count` and `fit_estimate`. So one row did two jobs:

- **The query,** written by the analysis: the title searched on the market,
  the title and description embedded to match postings, and the dimension
  keys the local fit estimate reads.
- **The last build's outcome,** overwritten by every build.

That mixed two lifetimes and two owners, and cost three things:

- **No history.** Nothing said what an earlier build made of the same
  candidate, and `compute_fits`' estimate-agreement log only ever saw the
  latest.
- **A second copy.** A placed role's openings are counted live (`map_roles`),
  so the candidate's `opening_count` could disagree with the bubble.
- **A hidden reason.** An empty `role_id` meant either "too few openings in
  your locations" or "enough openings, but others read more like you".

## Decision

- **A `RoleCandidate` is only the query:** `rank`, `title`, `description`,
  `dimension_keys` and `assessment_id`. A build never writes to it.
- **A build records a `CandidatePlacement` per candidate it read**
  (`rolemap.candidate_placement`, owned by `BuildRun` in `build_run.py`):
  - `outcome`: `placed`, `outside_top_k` (enough openings; the estimate kept
    others) or `too_few_openings` (fewer than a role needs). A check
    constraint ties `role_id` to `placed`.
  - `role_id`, `opening_count` and `fit_estimate`, as the candidate held them.
  - `rank` and `title` copied in, and `candidate_id` set null when the next
    analysis replaces the candidates, so the record still reads.
  - It goes with its build (`ON DELETE CASCADE`).
- **`recluster` is a build's work** and takes its `build_id`.
- **Readers take each candidate's newest placement.** `GET /role-candidates`
  answers with the same body as before, built from the candidate and its
  latest placement. A build that found nothing in scope places nobody, so the
  build before it still speaks for them. The estimate-agreement log reads
  placements too.
- **Migration 0026** writes one placement per current candidate against its
  owner's latest `ready` build, deriving the outcome from `role_id` and the
  opening count, then drops the three columns.

The outcome is named `too_few_openings` rather than the plan's
`no_openings`: a candidate with one or two openings is not without openings,
it is short of the three a role needs.

## Consequences

- **Easier.**
  - Each build's outcome is kept, so the estimate's agreement with the fits
    can be followed across builds.
  - Why a recommended role is missing is recorded, ready for the role map to
    say so.
  - The candidate has one writer, the analysis.
- **Harder.**
  - "Which role did this candidate become" is a lookup through the newest
    placement instead of a column.
  - One more table and repository, and a row per candidate per build (at most
    `ROLE_CANDIDATE_COUNT` per build). They are kept as long as their build,
    and builds are never pruned yet.
  - `recluster` needs a recorded build, so a test that calls it records one.
  - The migration has to guess outcomes for candidates placed before it, from
    counts that may already be stale.
  - The SPA does not show the outcome yet: that would change the response.

## Alternatives considered

- **Move the three fields onto `Role`.** A candidate the market lacks has no
  role to hold them, and that is the one the role map most needs to explain.
- **Keep the fields on the candidate and add the outcome beside them.** It
  names the reason but keeps the overwrite, the second copy and the two
  writers.
- **Store the outcomes as JSON on `build_run`.** Fewer tables, but nothing
  could be filtered by candidate without reading every build.
