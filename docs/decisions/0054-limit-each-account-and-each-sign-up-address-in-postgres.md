# 0054. Each account, and each sign-up address, is limited in Postgres

**Status:** Accepted — 2026-10-05.

## Context

Caddy limits what it can see: requests per connection address, and body
size (ADR 0053). Some limits need what only the app knows:

- **Sign-ups.** Addresses are not verified (`architecture.md` open question
  3), so a script can make thousands of accounts. Caddy's limit on
  `/auth/*` counts sign-ins and refreshes too, so it cannot be set low enough
  to stop that without locking out people signing in.
- **Uploads.** Each résumé, role of one's own and template PDF is stored,
  then read on the operator's machine (ADR 0051). One account can fill both
  places up.
- **Syncs.** Each is queued work on the operator's machine, and calls to
  GitHub or Jira on the user's token.

AI work needs nothing new. Each job runs one of its kind per Target at a time
(ADR 0042), spends the user's own key, and stops at their monthly budget.

Behind Caddy, every request reaches the api from Caddy's address unless the
api believes `X-Forwarded-For`. It must believe that header only from Caddy,
or a client could name any address it liked.

## Decision

- **A limiter in `kernel.limits`.** It is a fixed-window counter in
  `limits.counter`, keyed by a SHA-256 digest of the limit's name and its
  subject, so no address is stored.
  - `Limiter.record_attempt(limit, subject)` adds one in a short transaction
    of its own. An attempt that then fails still counts: these limits are
    against floods, not a quota of successes.
  - Past the limit it raises `RateLimitedError` with `retry_after_seconds`.
    The error handler answers 429 with `Retry-After`, in the usual envelope.
  - Windows are counted from the epoch, so a day's window starts at midnight
    UTC.
  - Each attempt sweeps windows more than two weeks old, along an index. A
    limit's window may be at most a week.
- **The limits are named once, in `wiring.limits`, from settings.**
  - `SIGNUPS_PER_ADDRESS_PER_DAY` (10) on `POST /auth/register`, by client
    address.
  - `UPLOADS_PER_ACCOUNT_PER_DAY` (30) on `POST /resumes`,
    `/own-postings/upload` and `/resume-templates/upload`, by account.
  - `SYNCS_PER_ACCOUNT_PER_HOUR` (6) on `POST /connections/{kind}/sync`, by
    account.

  A route records the attempt before it does any work.
- **The client's address.** uvicorn runs with `--proxy-headers` and believes
  `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`. On the droplet that is
  jsa_net's subnet; elsewhere it is `127.0.0.1`, which believes no one.
  Caddy, as the edge, sets the header from the connection and never passes
  on a client's own.
- **The SPA says when to try again.** The app's refusals carry the wait in
  their message ("Try again in 3 hours."). For the proxy's own 429 and 413,
  which have no envelope, the client writes one from the status and
  `Retry-After`. An error page that is not JSON no longer breaks the client.

## Consequences

Easier:

- No cache to add, run or lose: the counter lives in the Postgres beside the
  api.
- A refusal says what was limited and when it lifts, in the body and in
  `Retry-After`.
- A new limit is one `Limit` in `wiring.limits` and one line in a route.

Harder:

- **One more write per limited request.** Uploads, sign-ups and syncs are
  rare enough that it does not show.
- **A forgotten `FORWARDED_ALLOW_IPS` on the droplet fails safe but badly.**
  Every client looks like Caddy, so ten sign-ups a day covers everyone.
  `docs/deploy.md` lists it among the droplet's settings.
- **A fixed window lets a burst straddle its edge.** Up to twice the limit
  can pass in a short span around midnight UTC. A sliding window would cost
  a row per attempt.
- **One network's users share the sign-up limit,** as with Caddy's.
- **Counters are not tidied the moment a window ends.** They wait for the
  next attempt's sweep.

## Alternatives considered

- **Redis.** It is the usual home for counters, but it is one more container
  on a 2 GB droplet, for a handful of writes a day.
- **Counting rows that already exist** (accounts created per address,
  résumés per day). There is no address on an account, and nothing to count
  for a refused upload. Each limit would also be a different query.
- **Limiting in the proxy only.** Caddy cannot see the account, and cannot
  tell a sign-up from a sign-in once both are lumped under `/auth/*`.
- **`slowapi` and other in-process limiters.** They keep counts in memory,
  which a restart forgets.
- **Counting inside the request's own transaction,** as Phase 12's plan
  described. A failed request would roll its attempt back, so a flood of bad
  requests would never be limited.
