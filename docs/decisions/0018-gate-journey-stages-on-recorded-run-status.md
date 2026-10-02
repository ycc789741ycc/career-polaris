# 0018. Gate the journey's stages on the status each stage records while it runs

**Status:** Accepted — 2026-09-28. Amended by [0027](0027-fetch-the-market-only-when-a-build-needs-it.md).

## Context

Four kinds of background work feed the journey: a GitHub or Jira sync and a
résumé parse (01 Sources), an analysis (02 Strengths), and a role-map build
(03 Role map). Before this change only the first two left any trace while they
ran. A connection had no "syncing" state, and a résumé stayed `uploaded` until
it was parsed, or for good if parsing hit an unexpected error. An analysis or a
build recorded nothing until it had a result. The page said "reload in a
moment", and a failure reached only the worker's log.

Nothing made a stage wait for the one before it:
- an analysis started while a résumé was still parsing silently missed that
  résumé's evidence;
- a role map rebuilt during an analysis ran alongside it.

ADR 0006 already has the answer for one job's progress: write the row before
queueing, and let the page poll it. What was missing was a record for every
stage, and one place that holds the rules between stages.

That place cannot be `rolemap`. Import-linter's layers put `assessment` above
`rolemap`, because fit reads the roles. So `rolemap` cannot ask whether an
analysis is running.

## Decision

Every stage records its background work before it is queued, in the component
that owns it:

- `profile.source_connection.sync_started_at` is set when a sync is asked for,
  and cleared when it ends either way.
- A résumé is `uploaded` until parsed. An unexpected parse failure is now
  recorded as `failed` too, then re-raised.
- `assessment.analysis_run` holds one row per requested analysis:
  `running`, `ready` or `failed`, with the error's stable code. Closing a run
  records `AnalysisFinished` in the same transaction.
- `rolemap.build_run` holds one row per requested build: `waiting`, `running`,
  `ready` or `failed`. Only one build is open per user. Asking again while one
  is open returns that build, which is also what turns a crawl's stream of
  `PostingsChanged` into a single rebuild.

A new top-layer component, `advisor.activity`, reads those records together.
It has no tables. It holds the rules:

- **02 waits for 01, by refusal.** `POST /assessments` answers 409
  `sources_processing` while a sync or parse is running, and 409
  `analysis_running` while an analysis is. The Analyse button is disabled with
  the reason. An answered follow-up question still re-runs the analysis
  ungated, because its evidence is already stored.
- **03 waits for 02, by queueing.** A build asked for while an analysis runs is
  recorded as `waiting` and not queued. The dispatcher starts it on
  `AnalysisFinished`, whether that analysis succeeded or failed. The route that
  saves a new role count now records the build itself, so the page sees it at
  once. The dispatcher ignores `RoleCountChanged`.
- **Lost work stops blocking.** A sync, parse, run or build still showing as
  busy after `JOB_STALE_AFTER_SECONDS` (default 900) is treated as lost:
  - `GET /activity` reports it as `failed` with code `stale`, and changes
    nothing;
  - the next request for that stage closes it, so the gate and anything
    waiting on it are released.

  This is the sweeper ADR 0006 left out, applied only on reads.

`GET /activity` returns everything running for the user. The SPA's shell polls
it every two seconds while anything is busy, and stops when nothing is. It
shows:
- a running bar under the header on every screen;
- a dot on each sidebar step still working;
- a toast when a stage finishes or fails.

It also tells each screen to reload what the finished stage wrote.

## Consequences

Easier:
- The user can see background work on every screen, not just the one that
  started it, and a failed analysis or build says why.
- An analysis always reads the evidence the user just added.
- Two builds of one user's role map no longer run at once, and a burst of
  crawl events costs one rebuild.
- The Strengths and Role map screens reload by themselves when their stage
  finishes.

Harder:
- One more component, and one more set of contracts in `.importlinter`.
  `activity` has to stay a thin reader: a rule that belongs to one stage still
  goes in that stage's component.
- The shell polls while work runs, a request every two seconds per open tab.
- `stale` can mislabel a genuinely slow job. A build over 15 minutes shows as
  failed, and a new request starts a second one while the first may still
  finish. Raise `JOB_STALE_AFTER_SECONDS` if that happens.
- The worker tasks now take the id of their recorded run (`run_id`,
  `build_id`). A job queued by an older version fails, and the user asks again.
- Answering a question while sources are processing starts an analysis that
  the Analyse button would have refused. This is deliberate, and the one
  exception.

## Alternatives considered

- **Put the gate in `rolemap` and `assessment`.** Lost: `rolemap` sits below
  `assessment` and cannot read its runs without a cycle, and the rule would be
  split across two components.
- **Refuse a role-map build during an analysis, as for 01→02.** Lost: a rebuild
  is also triggered by the crawler and by saving k, where there is nobody to
  refuse, so it has to be able to wait.
- **Wait inside the job, by re-queueing it until the analysis ends.** Lost:
  it spins the `ai` queue, and the page could not tell "waiting" from
  "running".
- **Read Procrastinate's job table for status.** Lost for the same reasons as
  in ADR 0006: it knows a job ran, not what the failure means to the user.
- **A sweeper process for lost jobs.** Lost for now: judging staleness on read
  needs no new process, and nothing else yet depends on a lost row being closed
  promptly.
