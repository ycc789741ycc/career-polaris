# 0052. Work waits for the processing machine instead of being reported lost

**Status:** Accepted — 2026-10-05.

## Context

Since ADR 0051 the worker and the crawler run on the operator's own machine,
which is not always on. The api and Postgres stay up on the droplet, so a user
can start an analysis, a build, a plan or an export while the machine that
would run it is off. The job is recorded and queued (ADR 0006), and it runs
when the machine comes back.

Two rules assumed the worker was always up:

- **Lost work.** Work still running after `JOB_STALE_AFTER_SECONDS` is
  reported as lost and stops blocking the stages after it (ADR 0018).
  Counted from when the work was recorded, an analysis queued at night would
  read "This analysis stopped responding" by morning, although it had never
  started.
- **The market wait.** A build waits for its market sources up to
  `MARKET_WAIT_SECONDS`, then builds on what is stored (ADR 0027). With the
  crawler off, it would build on a market nobody had fetched.

Procrastinate keeps a heartbeat per worker, but not when the worker started,
so it cannot say how long the worker has been back. The crawler is not a
Procrastinate worker at all.

## Decision

- **Heartbeats.**
  - The worker and the crawler each write a row in `presence.process`: a
    process id, its unit, when it started and when it was last seen. Each
    refreshes its row every `PRESENCE_HEARTBEAT_SECONDS` (default 10) and
    deletes it on a clean stop.
  - The beat runs on a thread with its own connection
    (`kernel.presence.Heartbeat`). The crawler's embeddings and the worker's
    renders block the event loop, and a beat waiting behind them would read
    as the machine being away.
  - Rows silent for a day are deleted.
- **Up or away.** A unit is up while one of its processes was seen within
  four beats (`PRESENCE_MISSED_BEATS`). It has been up since the earliest
  start among those processes (`kernel.presence.get_presence`, on the
  database's clock, which wrote the times).
- **The lost-work limit counts only time the worker has been up**
  (`Staleness.is_stale(…, online_since=)`). It counts from the later of when
  the work started and when the worker came back. While the worker is away,
  nothing is lost and a queued run reads as running.
- **A build waiting for the market counts only time both are up.** Its
  deadline counts only while the crawler is up
  (`BuildRun.is_market_wait_over`). Its lost-work limit counts only while
  both the worker and the crawler are up.
- **`GET /activity` carries `processing`.** That is `is_worker_online`,
  `is_crawler_online` and each one's last heartbeat, which is the same for
  every user.
- **The SPA says so.**
  - Every cost estimate (`CostConfirm`) adds "Processing is offline; this
    starts when it is back". The user can still confirm, and the run is
    queued.
  - The running bar leads with "Waiting for the processing machine to come
    back" while work waits.
  - While the machine is away, the shell asks every 30 seconds rather than
    every 2, so the notice clears soon after it returns.
- **`crawler_rw` gets `presence.process`,** beside the shared market zone and
  the outbox. The row holds a process id and two times, and nothing about any
  user.

## Consequences

Easier:

- A user can start work at any time and trust it to run, and is told before
  confirming when it will not start at once.
- A queued run is never reported lost, closed or retried while nobody could
  have run it.
- When the machine comes back, every queued run gets a full window. A run
  that really stops after that is still reported lost.

Harder:

- **A worker that crashes and restarts resets the clock.** Its lost job is
  reported one full limit after the restart, not after the job started.
- **Another table, and another grant for the crawler.**
  `architecture.md` section 3 now lists it.
- **Every activity read makes one more small query.**
- **The away notice shows on every cost estimate,** including the résumé
  chat's revisions. The chat itself streams from the api and works while the
  machine is away; only drafts, sections and exports wait.
- **There is no per-run "queued" state.** A run waiting for the machine reads
  as running, with the bar's "Waiting for the processing machine" above it.

## Alternatives considered

- **Record when a worker picks each run up, and count from that** (what
  Phase 12's plan described). That needs a new column and a write in every
  job of five components, and a `queued` state everywhere a run is shown.
  Counting only up-time gives the user the same outcome, with one rule in
  one place.
- **Procrastinate's own heartbeats.** They say whether a worker is up, but
  not since when, so they cannot restart the limit when the worker returns.
  The crawler has no grant on the job schema either.
- **A heartbeat on the event loop.** It is simpler, but it falls silent
  during every long embedding batch, so the crawler would flicker away.
- **Raising `JOB_STALE_AFTER_SECONDS` to a day.** It costs no code, but a run
  that really died would block the stages after it for a day.
