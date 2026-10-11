# 0071. An analysis and the role-map build are separate; the user starts every build

**Status:** Accepted — 2026-10-11. Supersedes [0020](0020-analyse-ten-roles-and-build-the-map-after-every-analysis.md) where it builds the map after every analysis; its fixed count was already superseded by [0029](0029-set-the-candidate-count-and-the-top-k-as-settings.md).

## Context

Since ADR 0020 a successful analysis always builds the role map:
`activity.build_after_analysis` requests a build, and Analyze's estimate
(`AnalysisEstimate`) adds the build and its fits to the analysis, so the user
confirms all three at once. Pressing Analyze on 02 Strengths therefore also
spends a role-map build. The user hasn't seen their strengths yet, and hasn't
looked at 03 Roles, where the build's scope is decided.

That scope was chosen on the wrong screen. "Where you want to work" sat on
01 Sources, which collects facts about the user's work. A location isn't one of
those facts. It decides which postings the role map reads and which salary
bands it shows, and the user only saw what it changed on 03.

## Decision

- **An analysis builds nothing.** A successful analysis records the strength
  report and hands its candidate roles to the role map (ADR 0024), then
  stops. `AnalysisFinished` releases only a build the user asked for while the
  analysis ran (`release_build_after_analysis`, ADR 0018), whatever its
  outcome, so that build reads the new candidates. Nothing else requests,
  queues or prices a build on an analysis's behalf.
- **Analyze is priced as the analysis alone.** `GET /assessments/cost-estimate`
  answers a plain `CostEstimate`; `AnalysisEstimate` and its
  `analysis_cost_usd`, `role_map_cost_usd`, `fits_cost_usd` and `max_roles`
  are gone. A build is priced on 03 by `GET /roles/cost-estimate`, as before.
- **A build needs candidates.** `POST /roles/recluster` is refused
  (`validation_failed`) before any analysis has handed candidates over,
  unless the build would wait for an analysis that is running.
- **The map says when it is behind the strengths.** A finished build records
  the `skill_assessment_id` whose candidates it placed (migration 0054,
  backfilled through earlier builds' placements). `GET /role-map` adds
  `strengths_changed`, true once a newer analysis has handed over candidates.
  It sits beside `locations_changed` (ADR 0027).
- **Locations are chosen on 03 Roles**, above the map and its Build button,
  folded to chips once chosen, and read-only while a build reads them. The
  routes keep their paths. Changing them still builds nothing (ADR 0027).

## Consequences

Easier:

- Analyze spends only on the analysis. A user can read their strengths,
  analyse again, and build the map when they're ready, from the places they
  chose next to the button.
- The confirmation for Analyze is one number with one meaning.
- The location question sits where its effect is shown.

Harder:

- **Two confirmations for the whole journey instead of one.** That was ADR
  0020's reason for coupling them, and it is accepted. On CareerPolaris AI
  neither confirmation is shown (ADR 0067), so there it is two clicks.
- **A map can be stale against the strengths**, which never happened before.
  The role map and Strengths now say so, and rebuilding is the user's call.
  Fits are scored with each build, so until then the bubbles show fits against
  the previous analysis's scores.
- **A public contract changed.** The analysis estimate lost four fields,
  which matters to any client that read them. The SPA is the only client,
  and it changes in the same release.
- **A build carries one more column**, and builds from before migration 0054
  whose candidates were since replaced keep a null. They read as current.
- **Roles reads the locations** on every state of the page, including while a
  build runs.

## Alternatives considered

- **Keep building after every analysis, with the picker moved to 03.** A
  first-time user's first map would then be built on the baseline before
  they reach the place where locations are chosen, which spends one build
  they did not ask for.
- **Build after an analysis only when a location is chosen.** It removes that
  first wasted build, but leaves a rule that depends on a setting on another
  screen, and the user still can't analyse without paying for a map.
- **Build automatically when locations are first chosen.** That spends the
  user's key without being asked, which ADR 0027 already refused.
