# 0069. A build runs its per-role AI calls side by side, up to a setting

**Status:** Accepted — 2026-10-11.

## Context

A role-map build makes its AI calls one role at a time. `recluster` names each
changed role and estimates its bar (`rolemap.extract`, then
`rolemap.difficulty`), and `compute_fits` then scores each role whose fit is
not current (`rolemap.fit`). With `ROLE_MAP_TOP_K` at 10 and nothing to reuse,
that is about thirty calls in a row, at 10 to 30 seconds each. Besides waiting
for due market sources, which `MARKET_WAIT_SECONDS` caps, this is where a
first build spends its time.

The calls for different roles don't depend on each other. Each reads its own
postings or its own requirements and writes its own rows. Only a role's bar
reads its own extraction.

## Decision

- **A build's per-role calls run side by side**, at most
  `ROLE_MAP_AI_CONCURRENCY` at a time (default 4, at least 1, at most
  `ROLE_MAP_TOP_K`). One role's extraction and bar stay in order. Lineage,
  placements, the openings' fits and `RoleFitsComputed` still come after
  every role has finished. `1` is the old behaviour.
- **The same calls, the same prompts, the same results.** Only when they run
  changes, so a build spends what it spent before and its estimate is
  unchanged.
- **The first failure ends the job, as before.** It cancels the calls still
  running, and that error is raised on its own, not as a group, so the build
  records the same error code. Roles stored before it stay, and lineage and
  placements are not recorded, as when the calls ran one after another.

## Consequences

Easier:

- A first build's AI time drops to about a quarter at the default.
- The operator can tune it per place in `.env` without a release, and set it
  to 1 to go back.

Harder:

- **The user's own monthly cap can be overshot by more.** `BudgetGuard.check`
  compares what was spent with the cap before each call and reserves
  nothing. Calls checked at the same moment can together pass the cap by up
  to `ROLE_MAP_AI_CONCURRENCY` − 1 calls' cost, where one at a time passed it
  by at most the last call. Accepted because the build's total was estimated
  and confirmed before it was queued, and the default is small. The
  platform's key is unaffected: `SpendMeter` reserves each call's ceiling
  under a row lock, so concurrent calls can't pass its quota or ceilings.
- **A provider's rate limit is likelier to refuse a build.** One build sends
  up to that many calls at once, and an extraction prompt carries up to 12
  postings, so a low-tier key's tokens-per-minute limit is reached sooner.
  The gateway does not retry a 429. On the user's own key it is a
  `CredentialFailedError`: the key is marked failed and their jobs paused
  until they resume. On the platform's key the user is told CareerPolaris AI
  is unavailable. Lowering the setting is the remedy, down to 1.
- **Logs and ledger rows from one build interleave.** Nothing reads their
  order.
- **Tests whose stub provider answers from one queue** must run their builds
  at 1, because the replies are scripted role by role.
- **A build holds more database connections at once.** Each running role
  holds one only while it writes, well inside the pool.

## Alternatives considered

- **Keep the calls one at a time.** That's the simplest, but it leaves the
  longest part of a first build as it is.
- **One call for all roles.** That's a single prompt naming and scoring every
  role. It would change the prompts, their validation and what a failure
  loses, and a reply that large is slower and more likely to break the
  schema.
- **Reserve the user's spend like the platform's.** That would stop the
  overshoot, but it means a reservation table and settlement for every
  own-key call, for an overshoot of a few calls that the user already priced.
- **No limit.** Every changed role at once (up to k) is faster, but it hands
  a provider ten calls from one user at a time, which a low-tier key may
  refuse.
