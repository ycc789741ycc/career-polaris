# Job Searching Advisor

Turns the work someone has actually done — GitHub, Jira, their résumé — into a
picture of where they stand (a skill radar) and what is worth aiming at (a role
map of real openings), with every claim traceable to evidence.

All AI runs on **the user's own provider key**. The platform runs only the work
that needs no model: crawling, parsing, embedding, matching.

## Read these first

| Document | What it settles |
|---|---|
| `docs/domain_model.md` | The domain model, bounded contexts and the 14 decisions behind them |
| `docs/architecture.md` | Deployables, module dependencies, data and trust boundaries, the AI gateway, flows and technical decisions |
| `docs/plan.md` | Phase 1 / 2 / 3 scope |
| `docs/decisions/` | Decision records for choices that are costly to reverse |

The design guideline at `/Users/yoshi/repo/design-guideline` applies here too.

## Running it

Everything runs in a container. Install Docker and `make` — nothing else. There
is no Python, Node, `psql`, linter or migration CLI to put on your machine, and
a bare `npm`/`pip`/`pytest`/`alembic` anywhere in this repo means a target is
missing.

```
cp .env.example .env      # fill in every blank; nothing has a default that matters
make build-infra          # pull the pinned Postgres and MinIO images
make build-app            # build the prod images, plus the test images the gates use
make start-infra          # compose up, wait healthy, then the least-privilege DB roles
make start-app            # runs migrations to completion first, then api/worker/crawler/web
```

`build-app`, `start-app` and `stop-app` take `MODE=dev|prod`, default `prod`;
any other value fails. Each Dockerfile has three stages, each with its own tag:

| Stage | Tag | Used by |
|---|---|---|
| `prod` | `jsa-*:prod` | `MODE=prod`: `compose.yaml` alone, nothing mounted. The only image CI or a deployed environment uses, and the one `scan` scans. |
| `test` | `jsa-*:test` | Both test tiers and every gate, in either mode, never mounted. `build-app` builds it whichever mode you ask for. |
| `dev` | `jsa-*:dev` | `MODE=dev`: `compose.yaml` + `compose.dev.yaml`, with the repo bind-mounted. Local only — never pushed, never deployed. |

`start-app` never builds: if the image for the mode is missing it stops and tells
you which `make build-app` to run. Both modes migrate first. Only one mode runs at
a time — starting one replaces the other — and `stop-app` stops whichever is
running. The app itself never reads `MODE`.

### Developing with live source

```
make build-app MODE=dev   # once, and again after a dependency change
make start-app MODE=dev
```

Layers `compose.dev.yaml` on `compose.yaml`: your checkout's `backend/` and
`web/src` are bind-mounted read-only, and saving a file reloads what uses it —
the api through uvicorn's reloader, the worker through `watchfiles`, and the SPA
through the Vite dev server with hot module replacement, on the same port. A
save typically shows up within a couple of seconds.

- The **crawler** is mounted but does not reload, because it crawls as soon as
  it starts and would hit real job boards on every save. Restart it with
  `make stop-app && make start-app MODE=dev`.
- Changing **dependencies**, `vite.config.ts` or `package.json` needs
  `make build-app MODE=dev` — those live in the image, not the mount.
- In dev, `migrate` (which `start-app` runs first) sees the mounted source, so a
  migration you have just written applies without a rebuild.

Every source mount in the repo lives in `compose.dev.yaml` and nowhere else — never
as `-v` in a Makefile recipe. The overlay is deliberately not called
`compose.override.yaml`, because compose would merge that into prod automatically.

Hostnames in `.env` are compose service names on the `jsa_net` network, not
`localhost`. The only host-facing values are the `*_PUBLISHED_PORT` numbers,
which are what your browser and any database client connect to. They take this
repo's block, `21470`–`21474` (api, web, Postgres, MinIO, MinIO console), never a
common default like `8000`, `5173` or `5432`, so the stack runs beside other
projects without a bind failure. Containers keep their conventional ports inside
`jsa_net`.

`make test-unit` runs in a container with `--network none`, so it is hermetic by
construction rather than by convention. `make test-integration` runs on the
compose network and assumes infra is up and migrated — it tells you to run
`make start-infra` if it is not. Narrow either with `PATTERN=`.

`make lint`, `make typecheck` and `make scan` are their own gates, never folded
into a test target. `scan` covers Python dependencies, npm dependencies, and the
prod images themselves. It hands each image to Trivy as a `docker save` stream,
rather than mounting the Docker socket, which would give the scanner root on the
host.

Supporting targets, never dependencies of the above: `migrate`, `format`,
`gen-client`, `lock` (regenerates `backend/uv.lock` after a dependency change),
`logs`, `stats`, `disk-usage`, `clean-up-cache`, and `clean-up-infra` (the only
destructive one).

- `clean-up-cache` deletes bytecode, the pytest/mypy/ruff/import-linter caches,
  downloaded models in `.cache/` and `web/dist`. It never touches `.env`, `tmp/`,
  `.venv/`, `node_modules/` or `web/openapi.json`.

- `stats` is one snapshot of CPU, memory and processes for every container,
  measured against its limit, plus restart and OOM-kill counts. `disk-usage`
  shows free disk, volume sizes, the largest Postgres relations and object
  storage by bucket. Both only read, and `disk-usage` needs infra up.
- Every container has a memory, CPU and process ceiling and rotated logs. The
  defaults are optional `*_MEM_LIMIT` / `*_CPUS` / `DOCKER_LOG_*` settings in
  `.env`. Raise a limit there, never in the compose files, when `stats` shows a
  service near its ceiling or `oom_killed=true`.
- `format` and `lock` write to source, so they run through `compose.dev.yaml`,
  where the mounts live. They need the dev images (`make build-app MODE=dev`),
  and they run as your own uid, so the files they rewrite stay yours.
- `gen-client` mounts nothing. The OpenAPI document leaves one container on
  stdout and enters the next on stdin, so it runs from the test images and works
  in CI. Prettier is told not to touch the generated `schema.d.ts`; otherwise
  `format` and `gen-client` would keep rewriting each other's output.

Infra and the app are separate compose projects (`jsa-infra`, `jsa-app`) sharing
the `jsa_net` network, so an app target can never remove an infra container. App
images carry `pull_policy: never`: they are built locally, and a missing one
should fail rather than send compose to Docker Hub for a stranger's image of the
same name.

Base and tool images are pinned by version — never `latest` — in the
`Dockerfile`s and compose files. Configuration arrives at run time through
`--env-file`, so `build-app` produces one prod artifact that is promoted
unchanged; the SPA gets its settings from
a `config.js` the container writes at start, which is why there are no `VITE_`
variables.

## Shape of the code

```
backend/src/
  api/        FastAPI: main.py, dependencies, error envelope, routes/<component>.py,
              schemas/<component>.py (every request and response body)
  worker/     queue worker entrypoint and the outbox dispatcher
  crawler/    its own deployable: the crawl loop only — no secrets, no user data
  cli/        migrate, job-queue schema, baseline seed, OpenAPI export
  wiring/     composition root shared by every deployable: container, crawl (the
              crawler's own narrow wiring), queue (task registration), models
  kernel/     technical kernel, no domain: db, outbox, jobs, auth, crypto,
              storage, ai_gateway, fetch, embeddings
  advisor/    the application, one component per capability: identity · profile ·
              market · rolemap · assessment · target · gapplan · resume · activity
                __init__.py  the component's ONLY importable surface
                service.py  use cases; stored data only via domain/repositories.py
                domain/     entities, rules, events, repository interfaces: no I/O,
                            no framework, no kernel
                infra/      ORM models, mappers, SqlAlchemy repositories + unit of work, adapters
                factory.py  builds the component's services from a Database
                jobs.py     use cases the worker runs
              market/crawling/  board adapters, discovery, politeness, one crawl run
backend/tests/{unit,integration}/   each mirrors src/
web/          React + Vite SPA, on the prototype's Organic design system (ADR 0004)
```

The backend is packaged by component, as the design guideline requires (its ADR
0003; ours is ADR 0009). A component owns its domain model, use cases and data
access. Its `__init__.py` is its public API and its submodules are private: other components,
routes and the composition root use only its `__init__.py`. Routes, task
registration and entrypoints never live inside `advisor/`. `kernel/` stays
outside the application on purpose (ADR 0009).

Data crosses three shapes on its way out (ADR 0013). Entities stay inside a
component. `service.py` returns frozen `*View` dataclasses, the component's
contract with its callers. `api/schemas/<component>.py` builds the wire body
from a view, never from an entity, and the SPA's `web/src/api/types.ts` only
aliases the generated `schema.d.ts`. A new response field therefore goes in the
view, the schema and its `from_view`, then `make gen-client`.

Every `GET` list answers with a page — `{items, page, page_size, total}` — and
takes `page` and `page_size` through the shared `Paging` dependency; an omitted
`page_size` returns the whole list (ADR 0014). Each list has a named schema
(`RolePage`), and the SPA reads one with `api.items<RolePage>(path)`.

Repository interfaces are defined in each component's `domain/`, in entities and
value objects — never ORM types — and implemented in `infra/` (ADR 0011). Every
repository has the same six methods (`create`, `get`, `get_list`, `get_count`,
`update`, `delete`) and one filter per aggregate; `get_list` is newest first and
paged. The six are written once in `kernel.db.repository.SqlAlchemyRepository`,
with an in-memory twin for unit tests in `tests/unit/kernel/db/fake_repository.py`.
A component's `factory.py` builds its services from a `Database`; nothing else
constructs a repository. Only `infra/` imports SQLAlchemy.

Twenty-two `import-linter` contracts in `backend/.importlinter` enforce those
boundaries, and they run in CI. If one breaks, the design is wrong, not the
contract.

## Things that are deliberate

- **The journey only runs forward.** Sources → Strengths → Role map → Advisor
  (01–04): a step reads the ones before it, never the ones after. The role map
  is rebuilt and rescored when the user asks, so the strength report shows no
  fit, role or bar from it — comparing against a role is the role map's job.
  Likewise Sources lists the collected facts, filterable by source — "Your
  answers" among them — and nothing the analysis made of them, and asks
  nothing: questions come from a target role's gaps, in the Advisor's Fill
  the gap (ADR 0023). Strengths explains each score by its confidence.
- **A stage waits for the one before it, and says so while it does.** Every
  sync, parse, analysis and role-map build is recorded before it is queued
  (ADR 0006). An analysis is refused while a source still syncs or parses, and
  a role-map build asked for during an analysis waits and starts when it ends.
  Those rules live in `advisor/activity`, not in `rolemap`, which sits below
  `assessment` (ADR 0018). A build then waits for the market sources it reads
  to be fetched, and says which it waits for (`waiting_for`, ADR 0027). The shell polls `GET /activity` while anything runs,
  for the running bar. Work still busy after `JOB_STALE_AFTER_SECONDS` counts
  as lost.
- **The crawler holds no secrets and has no grant on any user schema.** It
  fetches only the sources a build marked due, and announces nothing: no market
  change is ever resolved to users, and nothing reads across users (ADR 0027).
- **A role map is built only when the user asks.** An analysis, "Rebuild role
  map" or a custom role, each with a cost they confirmed. Neither the market
  nor a change of locations builds one, because a build spends their key.
- **Privacy is a storage location, not a flag.** Pasted JDs live in
  `market_user.private_job_posting`, which the crawler role physically cannot
  reach.
- **Row-level security on every owner-zone table**, keyed on a per-transaction
  `app.user_id`. Forgetting a `WHERE owner_id` returns nothing, not someone
  else's rows.
- **We run our own sign-in.** Argon2id passwords, 15-minute access tokens
  held only in memory, and rotating refresh tokens in an httpOnly
  `SameSite=Strict` cookie stored hashed. A reused refresh token revokes its
  whole chain. There is no address verification or password reset yet — both
  wait on email delivery. Why, and what it costs: `docs/decisions/0001`.
- **The AI credential is write-only.** It can be set, tested, replaced or
  deleted; a read returns provider, model and the last four characters.
- **Nothing reaches an LLM except through `kernel.ai_gateway`**, which estimates
  cost, checks the budget, decrypts the key for exactly one call, validates the
  output against a Pydantic schema, and writes a ledger row.
- **AI output is untrusted.** Evidence ids it cites must exist in *that user's*
  profile or the whole response is rejected — that is the guard against invented
  claims.
- **Glassdoor, Indeed and LinkedIn are not crawled** (domain decision 6). Market
  data comes from public ATS job boards, schema.org JSON-LD career pages, the
  Himalayas public API for remote work (ADR 0025), and JDs users paste
  themselves.

## Phase 1 scope

In: accounts, GitHub and Jira connectors, résumé upload, LLM configuration,
market data from ATS boards and pasted JDs, the strength report, the role map,
and follow-up questions.

## Phase 2 scope

In: the gap plan — plan a route to a Target (a role, and optionally one opening
in it; ADR 0022), with gaps ranked by the fit points each is worth, milestones,
tasks and projects drafted on the user's key, versions per Target with finished
work carried forward, and plan history. `target` resolves what a plan aims at
and has no tables (ADR 0005). Drafting is a job whose row the page polls
(ADR 0006).

And the Resume Advisor: a résumé written for a Target from cited evidence, over
the uploaded résumé when there is one, with requirement coverage decided by
scores; in-place editing saved as versions; a revision chat streamed over SSE
whose proposals apply only on request; and PDF export on the worker's `docs`
queue with WeasyPrint (ADR 0007). Its routes are `/tailored-resumes` —
`/resumes` is the profile's upload endpoint.

Both live on one **Advisor** screen (`#/advisor/plan`, `#/advisor/resume`),
aimed at what the role map has selected: a role, and optionally one of its
openings. That selection is carried in the hash (`?role=`, plus `&opening=`),
so neither tab picks a Target of its own; the Advisor's "Your target role"
banner only links back. The role map has exactly one control that aims the
Advisor — the sticky "Advisor target" bar; picking a bubble or an opening only
selects.

Not yet: suggesting a successor Target when a Role splits (rolemap does not
emit `RoleSplitOrMerged` yet), and the interview-report prompt after a résumé
is tailored. The hiring bar is `estimated` only — `InterviewReport`
arrives with the reporting flow later.

## Phase 3 scope

In: sign in with Google — our own OpenID Connect exchange (PKCE, state, nonce)
whose callback lands on the api and ends in our own session, the same refresh
cookie a password sign-in sets. Outside identities live in
`identity.federated_identity`, keyed on Google's `sub`. A Google-verified
address takes over a password account at the same address and removes its
password and sessions, because our own addresses are unverified (ADR 0008).
Optional: blank `GOOGLE_OAUTH_CLIENT_ID` turns it off.

Not yet: unlinking Google, or linking it from Settings.

## Phase 5 scope

The v3 journey redesign, one branch per step (`docs/plan.md`), all built:

- **Target locations.** 01 Sources asks "Where you want to work": one to three
  places, a `market` domain rule (`chosen_target_locations`) checked again by
  the request schema. `PUT /target-locations` saves the whole set; a change
  emits `TargetLocationsChanged`, which since ADR 0027 builds nothing: the
  role map says the locations changed. The role map has no market pills or band
  toggle, and says how many open postings the locations take in
  (`GET /market-scope`). The table keeps its old name,
  `market_user.market_preference`. A location that is a country or "Remote"
  is searched on a public job API for the roles the analysis recommends
  (ADR 0025).
- **No watchlist** (ADR 0019). Role subscriptions, manual re-crawls and the
  `subscription` Target kind are gone. Board discovery stays as an ownerless
  `market.discover_board(company_id, company_name)`, for the companies custom
  roles will name; it leaves a company that already has a source alone.
- **Ten roles, built after every analysis** (ADR 0020). `RECOMMENDED_ROLE_COUNT`
  is a `rolemap` domain constant; there is no setting. `AnalysisFinished`
  goes to `activity.build_after_analysis`: a successful analysis always builds
  the map, a failed one only releases a build that waited. Analyze's estimate
  (`AnalysisEstimate`) includes the build's, so it is confirmed once.
- **Roles come from the strengths** (ADR 0024). The analysis recommends up to
  20 candidate roles; `assessment` hands them to `rolemap.replace_candidates`,
  and `rolemap.role_candidate` holds the latest set. A build matches them to
  the postings in scope locally (embeddings, plus title words) and keeps the
  first ten with openings; nothing clusters any more. With no candidates, a
  build places custom roles only. Fits are scored once per build, when
  `RoleMapBuildFinished` reaches the dispatcher, and every estimate that leads
  to a build includes them (`fits_cost_usd`). `GET /role-candidates` lets the
  role map name the recommended roles the market lacks.
- **Candidate roles are searched for** (ADR 0025). There is one ownerless
  `himalayas` crawl source per job title and place: a country, or "Remote"
  (`market.domain.search_scope`; a region adds none, ADR 0026). Only the title
  leaves the platform, and only the first page of each search is read. Remote
  work open worldwide is in scope for every listed location. An opening found
  there carries `credited_to` and is shown "via Himalayas" with its link.
  Since ADR 0027 a build asks for these searches itself (Phase 6).
- **Custom roles** (ADR 0021). `rolemap.role.origin` is `recommended` or
  `custom`; a custom role has an optional company and private JD, is never
  retired by reconciliation, and is removed by the user (retired, not deleted).
  Each build matches it to postings by title words (and company) through
  `market.names_every_word`, and reads requirements from its JD, else its
  matches. `POST /roles/custom` (priced by `/roles/custom/cost-estimate`) stores
  the JD and records the build; `CustomRoleAdded` sends the company to board
  discovery. Pasted JDs are no longer clustered, and every one belongs to a
  custom role.
- **A Target is a role, plus an optional opening** (ADR 0022). `TargetRef` is
  `(role_id, job_posting_id?)`; plans and résumés store both columns. A custom
  role's JD is its requirement basis, else the role's own; the fit is the
  role's, so resolving a Target spends nothing. `/targets` and the private-JD
  scoring path are gone; `GET /matched-postings?role_id=` lists a role's
  openings.
- **Fill the gap** (ADR 0023). A new `advisor/gapfill` component
  (`gapplan | resume | activity → gapfill → target`, schema `gapfill`) writes
  questions per gap of the Target on the user's key, polled while `writing`.
  One submit checks the whole batch, records every answer through
  `profile.record_answers` as `user_answer` evidence, and emits
  `GapAnswersSubmitted`; the dispatcher queues `gapplan.regenerate` and
  `resume.regenerate`, each a no-op without a plan or résumé. The old
  follow-up questions, `/questions` and their tables are gone. The Advisor
  opens on `#/advisor/gaps`.
- **Profile confidence on Strengths.** `assessment` returns
  `profile_confidence` with the strength report (the unweighted mean of the
  dimensions' confidence); Strengths shows it next to Re-analyse and lists
  dimensions least certain first. The sidebar has no meter. Résumés come in the
  prototype's two templates, `organic` and `plain`.

## Phase 6 scope

Building the role map only on demand (`docs/plan.md`), one branch per step:

- **Target locations from a list** (ADR 0026). A target location is one of
  `market.domain.places`: "Remote", a region (Asia-Pacific, Europe, Latin
  America, Middle East & Africa, North America) or a country, served by
  `GET /target-location-options` and picked in 01 Sources from a filterable
  list. `chosen_target_locations` stores each under its name on the list and
  refuses anything else. A country takes in its aliases and main cities
  (`place_names`), in `in_market` and the scope SQL; a region
  takes in its member countries and is never searched. Migration 0021 moved
  stored free text onto the list and deleted what named no place. Integration
  tests that need a market of their own store a made-up place directly
  (`tests/integration/places.py`).
- **The market on demand** (ADR 0027).
  - **What a build asks for.** A build asks
    `market.request_sources(titles, places, company_ids)` for every source it
    reads:
    - the candidates' searches in each searchable place;
    - the baseline boards;
    - its custom roles' companies' boards.

    Each is stamped as asked for. One whose last fetch is older than
    `MARKET_SEARCH_FRESH_HOURS` / `MARKET_BOARD_FRESH_HOURS` is marked due.
    A new search is inserted `ON CONFLICT DO NOTHING`.
  - **When it starts.** Nothing due: the build starts at once. Otherwise it
    waits; `rolemap.await_market` (queue `sync`, as the build's owner) checks
    every `CRAWL_DUE_POLL_SECONDS` and starts it when its sources are fetched,
    or after `MARKET_WAIT_SECONDS`. `wiring.queue.queue_build` turns any build
    request into the right job.
  - **The crawler.** It fetches only due sources, embeds, then clears
    `due_at`. It pauses a host after a 429 or 403 (honouring `Retry-After`),
    caps requests per host per day, and caches robots.txt for a day. Once a
    day it retires searches no build needed in `MARKET_SOURCE_IDLE_DAYS`, and
    thins postings nothing holds after `POSTING_THIN_AFTER_DAYS`:
    description and embedding dropped, row kept.
  - **Search results.** A search's fetch replaces its list in
    `market.search_result`. A searched posting is in scope only while it is on
    one. A board still expires what it stops listing.
  - **Choosing the ten.** A searched posting belongs to the candidate whose
    search found it, if relevant; otherwise it is dropped. The ten are picked
    by a free local fit estimate (`rolemap.domain.fit_estimates`) over the
    dimensions `assessment` hands over with the candidates
    (`rolemap.candidate_strength`). It is stored as `fit_estimate`, never
    shown as a fit; `compute_fits` logs its Spearman agreement with the fits.
  - **What's gone.** `PostingsChanged`, `RoleCandidatesReplaced`, the fan-out
    and its `fanout_read` policy, the weekly crawl and
    `market.request_searches`.
  - **What the user sees.** `GET /role-map` says how old the map's market is
    and whether the locations changed; the running bar and the Rebuild button
    say "Searching the market…".
- **The fit is the role map's** (ADR 0028). `RoleFit` (table
  `rolemap.role_fit`), its gaps, uncovered requirements and closing lifts,
  `compute_fits`, `estimate_fits` and the "Top matched" ranking live in
  `rolemap`; `assessment` keeps only the strength report. A fit is scored
  against the dimension scores `assessment` hands over with the candidates:
  `StrengthInput` and `rolemap.candidate_strength` carry `score` and
  `confidence`, and `weight` is their product. `RoleMapBuildFinished` queues
  `rolemap.compute_fits`. `/fits`, `/fits/compute` and `/matched-postings`
  keep their paths on the role map's router; a fit's body has no
  `private_posting_id`. Migration 0023 moved the fits and backfilled the
  scores.
