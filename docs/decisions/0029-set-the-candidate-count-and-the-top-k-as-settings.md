# 0029. Set the candidate count and the top k as settings, and spend only on the k

**Status:** Accepted — 2026-10-03. Amends [0020](0020-analyse-ten-roles-and-build-the-map-after-every-analysis.md) and [0024](0024-recommend-roles-from-the-assessment-and-keep-the-ten-the-market-has.md), and supersedes domain decision 23.

## Context

Two numbers decide what a role map costs. Both were constants in the
`rolemap` domain:

- **`CANDIDATE_ROLE_COUNT = 20`:** how many roles an analysis recommends. ADR
  0024 set it at twice the ten, so that a candidate the market lacks leaves
  room for the next. ADR 0027 searches each of them on Himalayas in every
  country or "Remote" the user picked: up to sixty searches for one analysis.
  The `skill_assessment` v2 prompt also says "up to 20".
- **`RECOMMENDED_ROLE_COUNT = 10`:** how many recommended roles a build keeps
  and analyses on the user's key. ADR 0020 fixed it "by the system, with no
  setting", to make the cost predictable, after ADR 0003's per-user choice
  proved hard to explain.

Neither can be tuned without a release. The searches load a shared,
rate-limited API (ADR 0027 caps requests per host per day). Each kept role
costs the user three calls: naming it, estimating its bar, and scoring its fit
(ADR 0028). The plan's open question was whether twenty candidates were worth
their searches. Answering it needs the number to move.

## Decision

Both numbers are deployment settings, read once at startup into `Settings`:

- **`ROLE_CANDIDATE_COUNT`,** default **10**, from 1 to 20: how many roles an
  analysis recommends. Every one is searched for.
  - The reply's schema allows at most that many, so a reply with more fails
    validation and the gateway asks again.
  - A new prompt, `skill_assessment` v3, states the number as an input
    (`{{candidate_count}}`). v2 is kept unchanged, as templates are.
  - `rolemap.replace_candidates` refuses more than that many.
- **`ROLE_MAP_TOP_K`,** default **10**, at least 1 and at most
  `ROLE_CANDIDATE_COUNT`: how many recommended roles a build keeps.
  - The local estimate (ADR 0027) picks the top k candidates with at least
    three openings. Only those k are named, analysed and fit-scored; nothing is
    sent to the model for the rest.
  - The rest are recorded unplaced, with their opening count and estimate, so
    `GET /role-candidates` still names them.
  - The estimates price k: the full k when the user has a searchable place,
    otherwise the most roles the stored postings can make, capped at k. The
    fits estimate counts at most k recommended roles.
- **Custom roles stay outside the k.** Every one is placed and scored, as
  before, because the user asked for it by name.
- **Where the numbers live.** `wiring.container` passes them through the
  components' factories. `RoleMapService` takes `top_k` and `candidate_count`,
  and refuses a k outside 1 to the candidate count. `AssessmentService` takes
  `candidate_count`. The selection rules take them as arguments
  (`max_role_count(…, ceiling=)`, `choose_by_estimate(…, limit=)`).
  `RECOMMENDED_ROLE_COUNT` and `CANDIDATE_ROLE_COUNT` are gone.

The default candidate count drops from twenty to ten, so a new analysis makes
half the searches. The default k stays ten, so a build costs what it did.

## Consequences

Easier:

- An operator can cut what one analysis asks of Himalayas, or what one build
  spends, from `.env`, without a release.
- A build never spends on more roles than it shows: the k it keeps is the k it
  names, analyses and scores, and the confirmed cost is priced for that k.
- The prompt and the schema agree on the number, so a reply cannot quietly
  carry roles nobody will search for.

Harder:

- What a build costs depends on the deployment. The cost confirmation still
  shows the real ceiling, but "ten roles" is no longer something a reader
  finds in the code or can promise in copy. The SPA says `max_roles`.
- With ten candidates instead of twenty there are fewer spares. In a narrow
  market where several candidates have under three openings, the map shows
  fewer than k roles. `candidates_on_market` in the `rolemap.selected` log is
  the number to watch.
- Two more settings to tune, with a cross-check between them. A k above the
  candidate count fails startup, rather than pricing roles no build can make.
- An analysis stored under v2 recommended up to twenty. Those candidates stay
  until the user analyses again, so a build until then still searches for all
  of them, and keeps the top k.

## Alternatives considered

- **Keep both constants.** Predictable, and what ADR 0020 chose. It lost
  because both numbers turned out to be tuning knobs: the search load and the
  cost per build both rest on them, and changing either meant a release.
- **Let each user choose k,** as ADR 0003 did. It lost for the reasons ADR
  0020 gave: the cost confirmation and the map's copy are harder to explain
  per user. A per-deployment setting gets the tuning without that.
- **Keep twenty candidates, analyse only k.** It keeps more spares, at twice
  the searches per analysis. With no evidence yet that the spares are used,
  the default halves the load; twenty is still one setting away.
- **Score fits only for the top k, but name and analyse every candidate with
  openings.** It shows more of the market, but spends two calls per extra role
  on roles the user never sees scored. Keeping, naming and scoring the same k
  keeps what is spent and what is shown the same.
