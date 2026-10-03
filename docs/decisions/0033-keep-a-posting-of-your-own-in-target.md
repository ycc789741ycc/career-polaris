# 0033. Keep a posting of your own in Target, and score it with the role map's fit kit

**Status:** Accepted — 2026-10-06. Amends [0005](0005-resolve-targets-in-their-own-module.md) and [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md). Amended by [0034](0034-add-a-role-of-your-own-without-evaluating-it.md).

## Context

ADR 0030 took pasted JDs off the role map. A user who finds no role or opening
worth aiming at in 03 Roles adds a posting of their own in 04 Advisor, and no
build reads it. But the concept was still spread across components that have
nothing else to do with it:

- Its JD lived in `market_user.private_job_posting`, in `market`, which is
  otherwise the shared market and the user's target locations.
- Its evaluation lived in `rolemap`. That covered the run, its requirements,
  the AI's fit and the worked-out fit. The worked-out fit sat in
  `rolemap.posting_fit` beside the openings' fits, kept apart by a `basis`
  column. ADR 0030 accepted that "`rolemap` scores something that is not on
  the map", and turned down putting the evaluation in `target`, because
  `target` had no tables (ADR 0005) and the fit rules would split.
- `target` only resolved one, through `rolemap.own_posting` and
  `rolemap.own_posting_fit`.

So a concept that belongs to the Advisor, and is used only to aim it, was
owned by the two components below it that it never feeds. Changing how a
posting of your own works meant changing `market` and `rolemap`, and reading
them to see what a Target is.

## Decision

A posting of the user's own is a Target, and `target` owns it end to end.

- **`target` gets tables**, in a new `target` schema. They are owner zone,
  under RLS, and the crawler has no grant on the schema.
  - `private_job_posting` holds the JD. It keeps the name its id has had
    everywhere (`private_job_posting_id`).
  - `posting_evaluation`, `posting_requirement` and `posting_requirement_fit`
    hold the runs, the requirements and the AI's evaluation.
  - `own_posting_fit` holds the fit worked out from them.
  - Each table references its posting with `ON DELETE CASCADE`.
- **`target` gets the full component layout**: `domain/`, `infra/`,
  `factory.py` and `jobs.py`. The use cases move into `TargetService`, the
  routes into `api/routes/target.py` with the same paths (`/own-postings`),
  and the job becomes `target.evaluate_own_posting`.
- **The fit rules stay in `rolemap`, lent as a stateless kit** through its
  public surface. It stores nothing for `target`:
  - `strengths(owner_id)` returns the scores a fit is scored against.
  - `extract_requirements(...)` reads a JD's requirements with the
    `role_extraction` prompt.
  - `project_requirements(...)` maps them onto the user's dimensions with the
    `fit_projection` prompt.
  - `get_projection_digest(...)` says whether a stored projection would come
    out the same.
  - `get_posting_fit_result(...)` works a posting's fit out from a projection,
    by the same arithmetic as an opening's. It is never an AI call.
  - `estimate_requirements` and `estimate_projection` price the two calls.
- **`market` and `rolemap` lose it.** `market` loses `PrivateJobPosting`, the
  paste methods and `GET /job-descriptions`, which nothing called.
  `rolemap.posting_fit` holds openings' fits only: it loses `basis`, and
  `role_id` becomes NOT NULL.
- **Migration 0030 moves the data, keeping every id**, so the plans, résumés
  and question sets aimed at a posting still name it. Migrations 0015, 0025
  and 0028 are guarded for a fresh database, where the baseline builds tables
  from the live models and the old tables and column no longer exist.

## Consequences

- **Easier.**
  - A Target is one place: what can be aimed at, and how it resolves.
  - `rolemap` means the role map again: roles, openings and their fits.
  - `market` means the market again.
  - The privacy rule is stated by the schema: the crawler cannot reach
    `target` at all.
- **Harder.**
  - `target` is no longer table-less. It has a schema, a migration history, a
    unit of work and a queue job to wire and keep in the contracts, against
    ADR 0005's "no tables".
  - `rolemap` has a public surface that exists only for `target`. The fit
    kit's shape is now a contract between the two. A change to how a
    projection is stored, or what it returns, touches both.
  - Scoring a posting of your own crosses a component boundary twice per run,
    so a unit test of it needs the role map's fakes as well as Target's.
  - Earlier migrations had to be edited to keep a fresh database buildable.
    That is the price of a baseline built from the live models, and every
    later table move pays it again.
  - A downgrade moves the data back, but the JD's canonical key is rebuilt
    from its company and title alone, and it has no embedding. Neither was
    read once it was a posting of the user's own.

## Alternatives considered

- **Leave it as ADR 0030 placed it.** This needs no migration, but the
  ownership stays upside down: two lower components keep a concept only the
  Advisor uses, and `rolemap` keeps a table that holds two kinds of fit.
- **Move the fit rules into `target` too.** Then the rules would be split: an
  opening's fit (ADR 0032) and a posting's own would be worked out by
  different code, and could disagree for the same requirements. `target` sits
  above `rolemap`, so it can borrow the rules but not lend them.
- **Move the JD only, and keep the evaluation in `rolemap`.** This is a
  smaller move, but `rolemap` would still store, per posting, rows keyed on an
  id it does not own, and Target would still resolve a posting of its own
  through the role map.
- **Rename the id to `own_posting_id`.** That is a better name for what it is
  now, but it appears in three other components' tables, every request body
  and query string, and the SPA's hash. Keeping `private_job_posting_id` and
  naming the table after it follows the naming rule at no cost.
