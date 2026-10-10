# 0068. A scope with no location chosen keeps only the newest baseline postings

**Status:** Accepted — 2026-10-11.

## Context

A user's role map is built from the open postings in their target locations.
A user who has chosen none gets the platform's baseline instead (domain
decision 15), so a first map has something to group before any setup.

The baseline is every open posting on every baseline board, worldwide, with
no location filter. GitLab, Cloudflare, Datadog, Stripe and Spotify each list
hundreds, so the baseline runs to a couple of thousand postings, and grows
whenever a board posts more. A user with a location usually reads far fewer.
So the user who did least setup gets the largest scope there is.

The size doesn't change what a build costs the user's key: the AI calls are
capped at `ROLE_MAP_TOP_K` roles and 12 postings a prompt. It does set the
worker's time and what crosses the tunnel. The worker runs on the compute
machine and Postgres on the droplet (ADR 0051). Each build reads the scope's
heads and vectors, embeds what the crawler hasn't, and compares every posting
with every candidate. The epic this record ships with already makes each of
those reads cheaper. This record bounds how many there are.

## Decision

- **With no location chosen, the scope is the newest
  `BASELINE_SCOPE_MAX_POSTINGS` open baseline postings** (default 500, at
  least 3). Newest is by the day a posting was posted, else the day it was
  first seen, then by when it was stored.
- **A location's scope is never bounded.** A user with one gets every posting
  that names it, plus worldwide remote, as before. They never get baseline
  postings outside it.
- **The bound is applied in one place.** `PostingScope.baseline_limit` is
  applied by the repository's scope query, so the role map, its estimate,
  `GET /market-scope` and every opening listing read the same set.
- **The user is told.** `GET /market-scope` returns `is_capped`, true when the
  count is at the bound. 03 Roles then says "The newest 500 open postings in
  the platform's baseline".

## Consequences

Easier:

- A first build reads at most `BASELINE_SCOPE_MAX_POSTINGS` postings, however
  many the baseline boards list. Its time and network use stop growing with
  the boards.
- The operator can tune the bound per place in `.env` without a release.

Harder:

- **Older baseline openings drop out of a no-location map.** A candidate role
  that only an older posting matched is not placed. The fewer it has, the
  sooner it is left out (`too_few_openings`).
- **A busy board can crowd out the rest.** If one board posts a lot in a
  week, the newest 500 can be mostly that employer's.
- **The count says less.** At the bound, "open postings in the baseline" is
  the bound, not the baseline's size. `is_capped` reports reaching the bound,
  so a baseline of exactly 500 also reads as capped.

## Alternatives considered

- **Refuse a build until a location is chosen.** That's the smallest scope
  there could be. But a first map before any setup is the reason the
  baseline exists (decision 15), and 01 Sources doesn't require a location.
- **Limit the baseline to worldwide-remote postings.** That would drop the
  boards listed for their on-site openings in Taiwan and Singapore, where no
  job API can be searched (ADR 0025).
- **Sample evenly per board.** That fixes crowding, but it adds a per-board
  rule to the scope query, and crowding hasn't been seen yet. It stays
  open as a refinement if it appears.
- **Leave the scope whole and only make reading it cheaper.** The same epic
  does that: heads instead of full postings, members by id, and cosines with
  numpy. On its own, it would still let a build's work grow with the boards.
