# 0020. Analyse ten roles, fixed by the system, and build the role map after every analysis

**Status:** Accepted — 2026-09-29. Supersedes [0003](0003-let-the-user-choose-how-many-roles-to-analyse.md). Amended by [0024](0024-recommend-roles-from-the-assessment-and-keep-the-ten-the-market-has.md) and [0027](0027-fetch-the-market-only-when-a-build-needs-it.md).

## Context

ADR 0003 let each user choose how many roles their role map analyses, between
3 and 20, stored in `rolemap.role_map_setting`. Changing it priced the new
count, saved it and rebuilt the map. Building the map was its own step: after
an analysis the user went to 03 Role map and pressed "Build role map", with a
second cost confirmation.

The v3 design changes both (domain decisions 23 and 24):
- The prototype's role map reads "The 10 best-fit roles on the market, plus the
  ones you add". The count input is gone. A user who wants further afield adds
  a role of their own (custom roles, the next step), which spends the key on a
  role they chose rather than on widening the automatic net.
- Analyze and the role-map build are one flow: an assessment finishes and the
  map is rebuilt from it. Two confirmations for one outcome was friction with
  no decision behind it.

## Decision

- **Ten, as a constant.** `rolemap/domain/selection.py` has
  `RECOMMENDED_ROLE_COUNT = 10`. `rank_by_fit` keeps the ten clusters closest to
  the profile, and `max_role_count(postings)` caps the estimate at ten. There is
  no setting: `RoleMapSetting`, `rolemap.role_map_setting` (dropped by
  migration 0014), `RoleCountChanged`, `/roles/settings`, `role_count` on the
  estimate and the SPA's count input are removed.
- **A successful analysis always builds the map.** On `AnalysisFinished`, the
  dispatcher asks `activity.build_after_analysis`. A `ready` analysis requests
  a build through `request_role_map`, with ADR 0018's rules: it starts a build
  that waited for the analysis, records a new one, or joins one already
  running. A `failed` analysis only releases a build that waited for it, as
  before.
- **One confirmation.** `GET /assessments/cost-estimate` returns the
  analysis's price plus the build's ceiling: `cost_usd` is the sum, with
  `analysis_cost_usd`, `role_map_cost_usd` and `max_roles` beside it. Strengths
  shows both parts. A later automatic rebuild (a market change, new target
  locations) needs no confirmation, as before.
- The role map keeps a "Rebuild role map" button, priced and confirmed, for a
  user who wants one without re-analysing.

## Consequences

Easier:
- The cost of Analyze is predictable, and the user confirms it once.
- The map is never behind the latest analysis, and nobody has to remember to
  build it.
- One setting, table and event fewer.

Harder:
- A user on a tight budget can no longer analyse fewer than ten roles. Every
  analysis now also pays for a build, though roles whose postings have not
  changed are kept without spending anything.
- A user considering a career change can't widen the automatic net. They add
  roles one at a time instead.
- Re-analysing to see new scores always rebuilds the map too, even when the
  user did not want it.

## Alternatives considered

- **Keep the user's k, and only build after analysis.** Lost: the prototype
  has no count, and custom roles cover the reason to raise it.
- **Build after analysis only when the user ticks a box.** Lost: a second
  decision for the common case, and a map that silently falls behind for
  anyone who leaves it unticked.
- **Let the worker queue the build with no confirmation at all.** Lost: the
  first build spends real money, and every AI action a user starts shows its
  cost first (domain 2.10).
