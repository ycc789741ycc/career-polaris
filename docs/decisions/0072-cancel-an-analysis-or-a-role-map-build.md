# 0072. The user can cancel an analysis or a role-map build

**Status:** Accepted — 2026-10-11.

## Context

Only the Advisor's jobs can be cancelled (ADR 0042). An analysis or a role-map
build runs to its end, spending the user's key or the platform's quota,
whether or not they still want it.

A dead job is worse. A worker killed mid-job (a deploy, `make stop-app`, or on
`local` every save of a `.py` file) leaves the `AnalysisRun` or `BuildRun`
row `running`, and nothing retries Procrastinate's job. Until
`JOB_STALE_AFTER_SECONDS` of worker uptime has passed, `GET /activity` shows
it running and Analyze answers `analysis_running`. Only then does
`advisor/activity` call it lost.

## Decision

- **A run can be `cancelled`.** `AnalysisRun` and `BuildRun` gain the status
  and `cancel(at)`. Only a running analysis, or a waiting or running build,
  can be cancelled. A cancelled run is closed (`is_running` and `is_open` are
  false), so every existing check treats it as finished. Migration 0055
  widens both status checks.
- **Cancelling marks the row**, so it works whether or not a worker is
  alive: `POST /assessments/runs/{run_id}/cancel` and
  `POST /roles/builds/{build_id}/cancel`, both 204 and idempotent, through
  `ActivityService.cancel_analysis` and `cancel_role_map`. Another owner's
  id is not found.
- **Cancelling an analysis cancels a build waiting for it** (one that has
  not yet asked the market). Since ADR 0071 only the user starts a build, and
  one asked for during an analysis waits so that it reads that analysis's
  candidates. Released, it would spend the key on a map from the analysis
  before. A build waiting for the market is left alone, and the sources it
  marked due stay due.
- **A live job stops itself**, as the Advisor's do (`kernel.progress`). It
  looks at its row through the gateway's progress callback, at a call's start
  and every `REPORT_EVERY_SECONDS` while the reply streams, and before it
  saves, and raises `JobCancelledError`. The analysis saves nothing. The
  build stops before its next role is stored, and records no lineage and no
  placements. A cancelled job is never recorded as a failure.
- **Events.** `AnalysisFinished` and `RoleMapBuildFinished` carry
  `status: "cancelled"`. The dispatcher releases nothing for the first and
  scores no fits for the second.
- **No confirmation on Cancel**, on either key. It costs nothing to cancel,
  and a call already sent is still charged and recorded in the ledger
  (ADR 0042).
- **What the user sees.** Cancel sits in the progress card's header on
  Strengths and Roles, and as "× Cancel" in the running bar's pill on every
  other screen; syncs and parses have none. It reads "Cancelling…" until
  `/activity` says the run closed. The toast says "Analysis cancelled.",
  "Role map build cancelled." or "Analysis cancelled, and the role map build
  that was waiting for it.", and a cancelled run is never shown as one that
  failed. `RunStatus` carries the `id` that Cancel names.

## Consequences

Easier:

- A user who changes their mind stops spending at once.
- A dead job no longer holds the journey for 15 minutes: cancelling it frees
  Analyze and Build immediately.

Harder:

- **A call already sent is still charged.** The user may pay for part of a
  run they cancelled. The wording never promises a refund.
- **A cancelled build can leave roles it already stored.** Each role is
  stored when its calls finish, so a cancel mid-build leaves the roles done
  so far, as a failed build already does (ADR 0069). The map isn't wrong, only
  incomplete until the next build. Lineage and placements are not recorded
  for it.
- **Every streamed call of an analysis and a build reads its run's row**
  every two seconds while it writes: a small, steady load on Postgres, over
  the tunnel for the compute machine (ADR 0051).
- **Analyses and builds now stream** through the gateway, because the
  progress callback is how they hear a cancel. Every provider already
  streams for the Advisor's jobs.
- **A third closed status** for the SPA and anything reading runs to handle.

## Alternatives considered

- **Leave it to staleness.** It costs nothing to build, but leaves a dead job
  blocking for 15 minutes and a live one spending after the user wanted it
  stopped.
- **Fail the run instead of a new status.** It reuses `failed`, but the
  report would say the analysis did not finish and Strengths would show a
  warning for something the user chose.
- **Release the waiting build when its analysis is cancelled**, as a failed
  analysis does (ADR 0018). That spends the key on a map from the previous
  analysis, which the user didn't ask for again.
- **Revoke Procrastinate's job as well.** Revoking the job only stops one
  that hasn't started. A started job has to look at its row anyway, so the
  row is the one signal.
