# 0024. Recommend roles from the strength assessment, keep the ten the market has, and score fits once per build

**Status:** Accepted — 2026-09-30. Amends [0020](0020-analyse-ten-roles-and-build-the-map-after-every-analysis.md), and supersedes domain decision 2. Amended by [0027](0027-fetch-the-market-only-when-a-build-needs-it.md).

## Context

The v3 design draws the role map as strengths first: the Analyzer recommends
the roles that best fit the user's strengths (2d), the background worker
searches the market for them (2e–2g) and builds the map (2h). The code does
the reverse, market first, following domain decision 2 ("Role catalog: grouped
by AI from postings") and ADR 0002:

- `RoleMapService.recluster` clusters every posting in the user's target
  locations with HDBSCAN (scikit-learn, used for nothing else), keeps the ten
  clusters whose embeddings are closest
  to the user's raw evidence facts and position titles (`rank_by_fit`), and
  only then names each one on the user's key.
- The strength assessment plays no part in choosing the ten. `rolemap` sits
  below `assessment` (ADR 0018) and cannot read it. The assessment comes back
  in only through fits, after the roles are fixed.

So `docs/domain_model.md` contradicts itself: the diagram's 2d arrow describes
one flow, and decision 2 and the glossary's `RoleSelection` describe the other.

ADR 0002 rejected "rank by the assessed fit" because a fit needs each role's
requirements, and getting them would spend the key on every cluster. That
objection assumed the roles have to exist before the assessment can say
anything about them. The analysis call already has the whole profile in
context, so it can name the roles the strengths point to at almost no extra
cost.

Fit scoring has a related problem. `assessment.compute_fits` is queued by
`AssessmentCompleted`, by `DimensionsChanged` (always recorded in the same
transaction, so it queues a second copy), and by every
`RoleRequirementsChanged` a build records, one per role it analyses. Each run
projects every role on the user's key. After an analysis:

- the first `compute_fits` scores the previous build's roles, or none on a
  first analysis, seconds before the build replaces them;
- a build that re-analyses all ten roles queues ten more, each scoring all ten:
  about a hundred `fit_projection` calls where ten would do;
- a build on an unchanged market keeps every role without recording an event,
  so the `AssessmentCompleted` trigger is the only thing that re-scores;
- none of it is in the Analyse estimate the user confirms.

## Decision

- **The analysis recommends candidate roles.** The `skill_assessment`
  template (v2) also returns up to `CANDIDATE_ROLE_COUNT` (20) candidates, best
  fit first, each with a title, a sentence or two on the work, and the
  dimension ids it rests on. The gateway validates them with the rest of the
  output; a candidate citing a dimension that is not in the same reply rejects
  the whole reply (`ai_output_invalid`), as an invented evidence id does. No
  extra call is made.
- **`rolemap` owns the candidates.** The glossary already files "Candidate
  role" under the role map. They live in `rolemap.role_candidate` (owner zone,
  row-level security), one set per user, replaced by each analysis.
  `assessment`, which already sits above `rolemap`, hands them over through
  `RoleMapService.replace_candidates` once its scores are stored. The build
  reads its own table, so `rolemap` never imports `assessment` and neither
  `activity` nor the `rolemap.recluster` job changes. Each candidate records
  the role the last build made of it, or none, and `GET /role-candidates`
  lists them for the role map to name the ones the market lacks.
- **"Search the market" means the crawled corpus.** No job platform is
  searched live (domain decision 6). Each candidate's title and description is
  embedded locally with the model the postings use. A posting in scope belongs
  to the candidate it is nearest to, when the cosine is at least
  `CANDIDATE_MATCH_THRESHOLD` (a `rolemap` domain constant, set against a
  fixture market when built), or when it names every word of the candidate's
  title (`market.names_every_word`, as custom roles match). A posting joins at
  most one recommended role.
- **The ten that exist.** A candidate with at least `MIN_POSTINGS_FOR_A_ROLE`
  matches is on the market. The first `RECOMMENDED_ROLE_COUNT` (10) of those,
  in the analysis's order, become the recommended roles. Fewer than ten is a
  valid map, and the role map names the candidates the market had no openings
  for. A market with fewer than `MIN_POSTINGS_FOR_A_ROLE` postings says nothing
  about the roles, so a build on one keeps them and the candidates as they
  are.
- **Identity, naming and the bar do not change.** `reconcile` still matches
  roles to their previous ids by posting membership. `_analyse` still names
  each role and reads its requirements and bar from its postings, so the name
  is the market's vocabulary rather than the candidate's. A role whose
  postings have not changed costs nothing to keep.
- **No assessment, no recommended roles.** A build before the first
  successful analysis places custom roles only.
- **Per-user clustering goes.** `rank_by_fit`, `_profile_vectors`, the
  HDBSCAN pass and `kernel.embeddings.cluster` are removed, and with them the
  direct `scikit-learn` dependency: nothing else clusters. `rolemap` no longer
  reads `profile`.
- **Fits are scored once per build.** `rolemap` records
  `RoleMapBuildFinished(build, status)` when a build closes, `ready` or
  `failed`, and the dispatcher queues one `assessment.compute_fits` for it.
  `AssessmentCompleted`, `DimensionsChanged` and `RoleRequirementsChanged` no
  longer queue it. `POST /fits/compute` stays for a manual re-score. Every
  estimate that leads to a build — Analyse, "Rebuild role map" and adding a
  custom role — adds `AssessmentService.estimate_fits`: one `fit_projection`
  per role the build can leave on the map, priced at the largest input it can
  have, and says so in `fits_cost_usd`. `RoleMapEstimate.max_clusters` is now
  `max_roles`.
- Domain decision 29 supersedes decision 2, and the glossary, the event flow
  and `architecture.md` change with the code.

## Consequences

Easier:
- The ten roles are the ones the assessment judged the best fit and the
  market actually has, rather than the clusters nearest an embedding of raw
  facts. This is what ADR 0002 wanted from "rank by the assessed fit", without
  a call per cluster.
- Recommended and custom roles take one path: a title searched in the corpus,
  then the same two calls.
- The worker no longer clusters every user's market on every build.
- The domain model's diagram and its decisions agree.
- A build's fits cost one projection per role, once, and the user sees that
  cost before confirming Analyse.

Harder:
- The map now depends on the model's judgement. A weak model proposes generic
  or overlapping titles, and two near-identical candidates split each other's
  postings until neither reaches the minimum. The template has to ask for
  distinct roles, including a few stretch roles.
- It leans towards what the user already is. Clustering showed adjacent roles
  nobody asked about. Now a role appears only if the analysis proposes it, and
  a career changer relies on custom roles.
- `CANDIDATE_MATCH_THRESHOLD` needs tuning: too low and a role absorbs
  unrelated postings, too high and the map comes up short.
- A rebuild on a market change uses the last analysis's candidates. They go
  stale when the profile moves until the user re-analyses, which is already
  how the strength report behaves (ADR 0015).
- A new table and a template version. `assessment` now writes to `rolemap`
  after storing its scores, in a second transaction: if that write fails, the
  run fails as `internal` with the scores kept, and the next build uses the
  previous analysis's candidates.
- A build already running when an analysis finishes is joined, not queued
  again (ADR 0018), so it reads the previous candidates. The next build — the
  next analysis, a market change or "Rebuild role map" — picks up the new
  ones. Candidates an analysis replaced mid-build are left for that build.
- The first build under the new rule reconciles against clusters, so most
  recommended roles retire and get new ids once. Plans and résumés aimed at
  them keep their snapshots, as for any retired role.
- Between an analysis finishing and its build finishing, the fits on screen
  still use the previous scores.

## Alternatives considered

- **Keep clustering (status quo).** Lost: the ten are chosen without the
  assessment, by similarity to raw evidence text, and the docs keep
  contradicting themselves.
- **Cluster, then let one call pick the ten against the assessment.** Lost:
  the prompt grows with the number of clusters (136 in ADR 0002's example),
  and a role smaller than the minimum cluster, or split across two clusters,
  can never be chosen.
- **Search job platforms live with the candidate titles.** Lost: there is
  nothing we may search. LinkedIn, Indeed and Glassdoor are out (domain
  decision 6), ATS boards are per company with no cross-company search, and
  board discovery needs a company name, which a candidate does not have.
- **Match candidates by title words only.** Lost: literal matching misses the
  same job under other names ("Platform Engineer" against "SRE II"), the
  weakness ADR 0021 already accepts for custom roles, where the user can add a
  JD. A recommended role has no JD to fall back on.
- **A separate call for the candidates after the analysis.** Lost: a second
  call and a second line on the estimate. The analysis already has the whole
  profile in context. It would allow new candidates without re-analysing, but
  nothing asks for that.
- **Keep fits on `AssessmentCompleted` and dedupe with a queueing lock.**
  Lost: it still pays to score roles that are replaced seconds later, and a
  per-owner lock would also drop the re-score a manual `POST /fits/compute`
  asks for.
