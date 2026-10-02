# 0027. Fetch the market only when a build needs it, and build the role map only when asked

**Status:** Accepted — 2026-10-02. Amended by [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md).

## Context

Until now the market moved the role map:

- The crawler crawled every source weekly. Between weekly runs it fetched the
  Himalayas searches an analysis's candidate roles asked for (ADR 0025).
- Each change became `PostingsChanged` about a company or a place.
- The worker's dispatcher resolved that to every user whose target locations
  took it in, through the one cross-user read in the system: a SELECT-only
  policy on `market_user.market_preference` gated on `app.fanout`.
- Each of those users got a rebuild and a `compute_fits` on their own key,
  whether they asked or not.

An analysis built the map twice. It built once at once from whatever was
crawled (ADR 0020), and again when its searches landed. That roughly doubled
the naming and fit calls on the user's key, and the map reshuffled under them.

Every build spends the user's key. The platform's own job is fetching,
parsing, embedding and matching, which spends nothing of theirs. So the map
should be built when the user asks, from a market fetched for that build.

Searches also had a rule that did not fit them. A search returns only its
first page, because Himalayas' robots.txt forbids paging. Expiring whatever a
fetch did not return read "pushed off page 1" as "closed".

## Decision

**A role map is built only on an action whose cost the user confirmed:** an
analysis, "Rebuild role map", or adding a custom role. A change of target
locations no longer builds; the role map says the locations changed, beside
its Rebuild button. Nothing the market does builds a map.

**A build asks the market for what it reads, and waits for what isn't fresh.**

- `market.request_sources(titles, places, company_ids)` resolves what a build
  needs:
  - a search per candidate title in each searchable place;
  - every baseline board;
  - the boards of the companies named on the user's custom roles.
- Each is stamped as asked for. One is **due** when its last fetch is older
  than its window, `MARKET_SEARCH_FRESH_HOURS` (72) for a search and
  `MARKET_BOARD_FRESH_HOURS` (24) for a board.
- A fresh source is reused, whoever's build fetched it. Marking is
  idempotent, so builds that need the same stale source wait on one fetch.
- A new search is inserted with `ON CONFLICT DO NOTHING`, so two analyses
  recommending the same title at once share one row.
- Only titles, places and company ids reach `market`, never a user id.

**The crawler fetches only due sources.**

- It looks every `CRAWL_DUE_POLL_SECONDS` (15) and fetches each due source.
- It stores and embeds what it found, and only then clears `due_at`. A build
  that starts on a source therefore finds its vectors.
- A failed fetch counts as fetched.
- The weekly run, the look for unfetched sources and every announcement are
  gone.

**A build waits for its due sources, checked by its own deferred job.**

- `rolemap.build_run` records the sources the build needs, the ones it waits
  for, when it asked, and the locations it was built for.
- A `rolemap.await_market` job runs as that build's owner on the `sync` queue.
  It starts the build once every source it waits for is fetched, or once
  `MARKET_WAIT_SECONDS` (300) has passed since it asked; otherwise it defers
  itself again.
- Nothing reads across users to find whom a fetch was for.
- A build asked for during an analysis still waits for it (ADR 0018), and
  asks the market when the analysis ends.
- `GET /activity` says what a waiting build waits for (`waiting_for`:
  `analysis` or `market`).
- The deadline must be shorter than `JOB_STALE_AFTER_SECONDS`, and the
  staleness clock for a waiting build runs from when it asked the market.

**A search's fetch replaces its result list.**

- `market.search_result` holds what each search returned last time.
- A searched posting counts in a scope only while it is on a current list.
  It is never expired for missing from a page, so it stays open while
  another search, or a company board, still returns it.
- A board still lists everything its company has, so a board posting missing
  from a fetch is expired, as before.

**The search decides which candidate a posting belongs to:**

- A posting a candidate's own search found goes to that candidate, if its
  title names the candidate or its embedding is at least 0.40 similar.
- One that is relevant to none of the candidates that searched for it is left
  out. Himalayas matches the query against descriptions, so some of what it
  returns isn't the job.
- Board postings are matched as before.

**A local estimate picks the ten.** Every candidate with three or more
openings gets a fit estimate computed on the platform's embedding model, with
no tokens:

- each of the user's dimensions is embedded from its name and the analysis's
  read of it;
- it is weighted by score × confidence, fully for the dimensions the
  candidate rests on and a quarter for the rest;
- it is compared with the centroid of the role's openings, centred per
  dimension so a broad strength lifts no role.

The ten best estimates are named and fit-scored, so the paid calls per build
are unchanged. The estimate is stored on the candidate and never shown as a
fit. Each `compute_fits` logs its rank correlation with the fits scored.
`assessment` hands the dimension names, reads and weights to `rolemap` with
the candidates (`rolemap.candidate_strength`), so `rolemap` still imports
nothing from `assessment`.

**The crawler is polite under demand:**

- A 429 or 403 pauses the host until its `Retry-After`, or for a backoff
  doubling from 15 minutes up to 6 hours.
- `CRAWL_MAX_REQUESTS_PER_HOST_PER_DAY` (500) is a ceiling no demand breaks.
- robots.txt is cached for a day across polls.
- A source on a paused or spent host stays due. The builds waiting for it
  start at their deadline on what is stored.

**What nobody asks for stops taking room.** Once a day the crawler:

- retires the searches no build has needed in `MARKET_SOURCE_IDLE_DAYS` (90),
  emptying their lists;
- thins the postings nothing holds that nobody has seen in
  `POSTING_THIN_AFTER_DAYS` (180). Their description and embedding are
  dropped. The row stays, so a Target's `job_posting_id`, an old map's
  members and salary history still resolve.

`market` decides all of this from its own rows, because it can't see who
references a posting.

**The fan-out goes.** `PostingsChanged`, `RoleCandidatesReplaced`,
`market.owners_affected_by`, the `market.request_searches` job and the
`fanout_read` policy are removed. Migration 0022 drops the policy.

`GET /role-map` says how old the market behind the map is (the oldest fetch
among the sources its last build read) and whether the target locations
changed since.

This supersedes domain decision 14 (weekly crawl). It amends ADR 0018 (a
build may wait for the market as well as for an analysis), ADR 0020 (one
build per analysis, after its searches), ADR 0024 (the ten are chosen by the
estimate, not the analysis's order) and ADR 0025 (no weekly crawl,
announcements or idle retirement by weeks).

## Consequences

Easier:

- One build per analysis, and nothing spends the user's key unasked.
- A re-analysis inside the window fetches nothing and builds at once.
- Searches are shared across users, so a popular title costs Himalayas one
  request per window however many people want it.
- There is no cross-user read left. The crawler says nothing that is ever
  resolved to a user, and no policy exists to widen by mistake.
- Pushed-off-the-page jobs no longer flap between open and expired.
- The ten roles are those most like the user's strengths, at no extra cost.

Harder:

- The map is only as current as the user's last request. A month-old map
  shows month-old openings until they rebuild. The screen says "Market data
  as of …", and "rebuilds and rescores as the market moves" is no longer
  true.
- A build arrives later when its sources are stale: up to the crawler's poll
  plus the fetches, bounded by `MARKET_WAIT_SECONDS`. A slow or refusing
  Himalayas, or a stopped crawler, costs the searched postings, not the map.
- Closed openings on a board stay open until some build fetches that board.
  A job pushed off a search's first page leaves the next map though it may
  still be open.
- Salary-band history grows only when someone builds.
- A user coming back after months finds thinned openings on their old map:
  title, company and link, with no description, until they rebuild.
- A region-only user's recommended roles are never searched for on their
  behalf. They see board postings and what other users' searches found.
- A custom role's company board, found by discovery after the build that
  added it, is read by the next build, not that one.
- The ten are chosen by a coarse estimate the user never sees. It can keep a
  role the analysis ranked low and drop one it ranked high, and the fits
  scored afterwards may disagree. The logged correlation is the evidence for
  keeping it.
- Seven new settings, each a default someone has to tune.

## Alternatives considered

- **Keep the immediate build and rebuild when the searches land** (today).
  Lost: two builds per analysis on the user's key, and a map that reshuffles
  minutes after it appears.
- **Keep the weekly crawl and the fan-out, but let only a waiting build
  hear "search done".** Lost: every market change still rebuilt every user in
  that place on their key, and the cross-user read stayed.
- **A worker loop that reads every waiting build to start the ready ones.**
  Lost: that loop reads builds across users, a second cross-user read. A
  deferred job per build checks only its owner's own row.
- **Expire searched postings by age** instead of replacing result lists.
  Lost: a posting no search re-checks would sit in scope until its age ran
  out, and the age would be a second knob beside the fresh window. A list
  replaced on each fetch says exactly what the search shows now.
- **Delete stale postings.** Lost: plans, résumés and gap questions refer to
  postings by id across schemas, and salary history needs the rows. Thinning
  keeps every reference whole.
- **Rank the ten by the analysis's own order** (ADR 0024). Lost to the
  estimate because the estimate uses what the market actually returned and
  costs nothing. Kept as the tie-break, and as the fallback if the logged
  correlation shows the estimate is no better.
