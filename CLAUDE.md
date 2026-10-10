# CareerPolaris

Formerly Job Searching Advisor. Since ADR 0056 every name inside the code base
is CareerPolaris's — the `careerpolaris-*` images, `careerpolaris_net`, the
`careerpolaris-infra` / `careerpolaris-app` compose projects, cookies, the
crawler's user agent — and `jsa` is not used for anything new. Since ADR 0059
the Git repository is `career-polaris` too. A machine that ran the old stack
copies its volumes across once, by hand, with the commands in ADR 0056; the
repo carries no command for it.

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
cp .env.example .env          # fill in every blank; nothing has a default that matters
cp .machine.example .machine  # this checkout is the `local` machine
make build-infra              # pull the pinned Postgres and S3 gateway images
make build-app                # build this machine's images, plus the test images the gates use
make start-infra              # compose up, wait healthy, then the least-privilege DB roles
make start-app                # runs migrations to completion first, then api/worker/crawler/web
```

**What runs where is the machine, not `.env`** (ADR 0062). Each checkout names
its machine in `.machine` (git-ignored), a folder in `deploy/` holding that
machine's two compose files, `compose.app.yaml` and `compose.infra.yaml`. They
pick their services from `deploy/compose.app.base.yaml` and
`deploy/compose.infra.base.yaml` with `extends`, and say, as literals, what
depends on the machine: which services run, memory, CPU and process ceilings,
log rotation, Postgres's sizing, published ports, the image stage, and the
project and network names.

| Machine | Runs | Images | Names |
|---|---|---|---|
| `local` | everything, source bind-mounted and reloading | `dev` | `careerpolaris-{app,infra}-local`, `careerpolaris_net_local`, ports 21470–21473 |
| `ci` | everything but the proxy, nothing mounted | `prod` | `careerpolaris-{app,infra}-ci`, `careerpolaris_net_ci`, ports 21474–21477 |
| `droplet-1vcpu-2gb` | api, web, proxy (ADR 0053), Postgres, tunnel | `prod`, pulled | `careerpolaris-{app,infra}`, `careerpolaris_net` |
| `compute-m5pro-48gb` | worker, crawler, tunnel | `prod`, pulled | `careerpolaris-{app,infra}`, `careerpolaris_net` |

`.env` holds only what the application reads, and every secret; `make lint`
fails if a machine's shape — `*_MEM_LIMIT`, `*_CPUS`, `DOCKER_LOG_*`,
Postgres's sizing, published ports, `COMPOSE_PROFILES` — comes back to
`.env.example`. Raise a limit in the machine's file, by pull request, when
`make stats` shows a service near its ceiling or `oom_killed=true`.

Because the development and deployed machines use different names, a
development clone runs beside production on the compute machine (the
operator's Mac) without either touching the other. Every target that starts,
stops or replaces containers or data refuses a stack another checkout started,
and says which (`scripts/check-stack-owner.sh`).

**There is no `MODE`**; passing one fails. The machine decides the image. Each
Dockerfile has three stages, each with its own tag:

| Stage | Tag | Used by |
|---|---|---|
| `prod` | `careerpolaris-*:prod` | Every machine but `local`, nothing mounted. The only image CI or a deployed environment uses, and the one `scan` scans. |
| `test` | `careerpolaris-*:test` | Both test tiers and every gate, never mounted. `build-app` builds it on every machine. |
| `dev` | `careerpolaris-*:dev` | `local`, with the repo bind-mounted. Never pushed, never deployed. |

`start-app` never builds: if an image the machine runs is missing it stops and
tells you to run `make build-app` (or, on a deployed machine,
`make pull-app RELEASE=release.env`). Every machine migrates first. The app
itself never reads which machine it is on. To run the prod images on a laptop,
use a second clone whose `.machine` says `ci`; `make scan` runs there, as in CI.

### Developing with live source

On `local`, `make build-app` (once, and again after a dependency change) then
`make start-app`. Your checkout's `backend/` and `web/src` are bind-mounted
read-only, and saving a file reloads what uses it — the api through uvicorn's
reloader, the worker through `watchfiles`, and the SPA through the Vite dev
server with hot module replacement, on the same port. A save typically shows up
within a couple of seconds.

- The **crawler** is mounted but does not reload, because it crawls as soon as
  it starts and would hit real job boards on every save. Restart it with
  `make stop-app && make start-app`.
- Changing **dependencies**, `vite.config.ts` or `package.json` needs
  `make build-app` — those live in the image, not the mount.
- `migrate` (which `start-app` runs first) sees the mounted source, so a
  migration you have just written applies without a rebuild.

Every source mount in the repo lives in `deploy/local/compose.app.yaml` and
nowhere else — never as `-v` in a Makefile recipe.

Hostnames in `.env` are compose service names on the machine's network, not
`localhost`. The only host-facing numbers are the published ports in the
machine's files, which are what your browser and any database client connect
to. They take this repo's block, `21470`–`21477`, never a common default like
`8000`, `5173` or `5432`, so the stack runs beside other projects without a
bind failure. Containers keep their conventional ports inside the network.

`make test-unit` runs in a container with `--network none`, so it is hermetic by
construction rather than by convention. `make test-integration` runs on the
compose network and assumes infra is up and migrated — it tells you to run
`make start-infra` if it is not. Narrow either with `PATTERN=`.

`make lint`, `make typecheck` and `make scan` are their own gates, never folded
into a test target. `scan` covers Python dependencies, npm dependencies, and the
prod images themselves. It hands each image to Trivy as a `docker save` stream,
rather than mounting the Docker socket, which would give the scanner root on the
host. It audits only what ships (`uv export --no-dev`, `npm audit --omit=dev`).
Because advisory databases move daily, CI's scan blocks only a version tag and
a change to what it reads (`.github/workflows/scan-gate.sh`); elsewhere a
finding is a warning, and the daily `scan.yml` on master opens one issue for it
(ADR 0063). A fix nobody can take yet is excepted with a reason and an expiry,
at most 30 days, in `.trivyignore.yaml` or `backend/pip-audit-ignore.txt`.
Between pushes, Dependabot (`.github/dependabot.yml`) opens security
updates as advisories land and weekly grouped bumps, each held a week
(`cooldown`); CI gates its PRs like any other. It cannot see images pinned in
the Makefile, which stay manual. It never rebases on its own (comment
`@dependabot rebase`), ESLint and its plugins arrive as one PR, and the Python
and Node versions and TypeScript's major are upgraded on purpose, not by it.

Supporting targets, never dependencies of the above: `migrate`, `format`,
`gen-client`, `lock` (regenerates `backend/uv.lock` after a dependency change),
`logs`, `stats`, `disk-usage`, `backup-db`, `release BUMP=` (tags
`origin/master` with the next version and pushes it), `push-app` (CI's release) and
`pull-app RELEASE=release.env` (a deployed place's), `check-env` (a deployed
place's `.env` against `.env.example`, whose `# may-be-blank:` line names the
optional settings), `clean-up-cache`, and the
two destructive ones, `restore-db BACKUP=` and `clean-up-infra`, which ask first.

- `clean-up-cache` deletes bytecode, the pytest/mypy/ruff/import-linter caches,
  downloaded models in `.cache/` and `web/dist`. It never touches `.env`, `.machine`, `tmp/`,
  `.venv/`, `node_modules/` or `web/openapi.json`.

- `stats` is one snapshot of CPU, memory and processes for every container,
  measured against its limit, plus restart and OOM-kill counts. `disk-usage`
  shows free disk, volume sizes, the largest Postgres relations and object
  storage by bucket. Both only read, and `disk-usage` needs infra up.
- Every container has a memory, CPU and process ceiling and rotated logs, as
  literals in its machine's files in `deploy/`. Raise a limit there, by pull
  request, never in `.env`, when `stats` shows a service near its ceiling or
  `oom_killed=true`.
- `format` and `lock` write to source, so they run through
  `deploy/local/compose.app.yaml`, where the mounts live, on any machine. They
  need the dev images (`make build-app` in a `local` checkout), and they run as
  your own uid, so the files they rewrite stay yours.
- `gen-client` mounts nothing. The OpenAPI document leaves one container on
  stdout and enters the next on stdin, so it runs from the test images and works
  in CI. Prettier is told not to touch the generated `schema.d.ts`; otherwise
  `format` and `gen-client` would keep rewriting each other's output.

Infra and the app are separate compose projects (on the droplet and compute,
`careerpolaris-infra` and `careerpolaris-app`; elsewhere with the machine's
suffix) sharing the machine's network, so an app target can never remove an
infra container. App
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
              storage, ai_gateway, fetch, embeddings, presence, limits
  advisor/    the application, one component per capability: identity · profile ·
              market · rolemap · assessment · target · gapplan · resume · activity
                __init__.py  the component's ONLY importable surface
                service.py  use cases; stored data only via domain/repositories.py
                domain/     one module per concept (role.py, build_run.py), holding its
                            entities, value objects and rules; plus repositories.py,
                            events.py and constants.py. No I/O, no framework, no kernel
                infra/      ORM models, mappers, SqlAlchemy repositories + unit of work, adapters
                factory.py  builds the component's services from a Database
                jobs.py     use cases the worker runs
              market/crawling/  board adapters, discovery, politeness, one crawl run
backend/tests/{unit,integration}/   each mirrors src/
web/          React + Vite SPA, on the prototype's Organic design system (ADR 0004)
proxy/        Caddy plus caddy-ratelimit, the edge on the droplet (ADR 0053)
deploy/       compose bases, and one folder per machine with its app and infra files (ADR 0062)
scripts/      DB roles, health wait, tunnel, backups, releases, env checks
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

A component's `domain/` is split by concept, as the design guideline's "Modules
in the domain: one per concept" requires (Phase 7). A module holds one
concept's entities, value objects, enums, errors and rules, and is named for it.
There is no `entities.py`. Only three modules are split by kind:
`repositories.py`, `events.py`, and `constants.py`, which holds every public
literal value and imports only the standard library. The rest of the
component imports from `domain/__init__.py`, so a class can move between
concept modules without changing any import outside `domain/`.
`tests/unit/advisor/test_domain_layout.py` keeps it that way.

Twenty-three `import-linter` contracts in `backend/.importlinter` enforce those
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
- **A role map is built only when the user asks.** An analysis, or "Rebuild
  role map", each with a cost they confirmed. Neither the market
  nor a change of locations builds one, because a build spends their key.
- **Privacy is a storage location, not a flag.** Pasted JDs live in
  `target.private_job_posting`, in a schema the crawler role has no grant on,
  so it physically cannot reach them.
- **Row-level security on every owner-zone table**, keyed on a per-transaction
  `app.user_id`. Forgetting a `WHERE owner_id` returns nothing, not someone
  else's rows.
- **We run our own sign-in.** Argon2id passwords, 15-minute access tokens
  held only in memory, and rotating refresh tokens in an httpOnly
  `SameSite=Strict` cookie stored hashed. A reused refresh token revokes its
  whole chain. There is no address verification or password reset yet — both
  wait on email delivery. Why, and what it costs: `docs/decisions/0001`.
- **Atlassian is told which accounts we hold data about** (ADR 0061). Each
  Jira connection keeps its `accountId` and reports itself weekly
  (`profile.report_jira_account`, one queueing lock per user) with the token of
  the operator's own Jira connection, `JIRA_REPORTING_OWNER_ID` (blank: off).
  A `closed` reply disconnects it, erasing every Jira fact. Jira tokens last an
  hour and are refreshed before use; the refresh token rotates.
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
(ADR 0005); since ADR 0033 it also keeps the postings of the user's own. Drafting is a job
whose row records its stage (ADR 0006); since ADR 0042 it runs in the background
— the shell lists it in `GET /activity`, the tab shows a card with Cancel, and
the other tabs stay usable — so a drafting plan is no longer a page the user
waits on.

And the Resume Advisor: a résumé written for a Target from cited evidence, over
the uploaded résumé when there is one, with requirement coverage decided by
scores; in-place editing saved as versions; a revision chat streamed over SSE
whose proposals apply only on request; and PDF export on the worker's `docs`
queue with WeasyPrint (ADR 0007). Its routes are `/tailored-resumes` —
`/resumes` is the profile's upload endpoint.

Both live on one **Advisor** screen (`#/advisor/plan`, `#/advisor/resume`),
aimed at the Target the user set: a role from the map (and, for a Target set
before ADR 0049, one of its openings), or a role of their own. It is carried in
the hash (`?role=`, plus `&opening=`, or `?posting=`) and remembered in the
browser (ADR 0050), so neither tab picks a Target of its own; the Advisor's
"Your target role" banner only links back, or switches to a previous target. The role map has exactly one control that aims the
Advisor — the sticky "Advisor target" bar, at the selected role (ADR 0049);
picking a bubble only selects.

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
  `subscription` Target kind are gone. Board discovery stayed, for the
  companies custom roles named, until Phase 8 removed both (ADR 0030).
- **Ten roles, built after every analysis** (ADR 0020). Since ADR 0029 the
  ten is the `ROLE_MAP_TOP_K` setting (Phase 6). `AnalysisFinished`
  goes to `activity.build_after_analysis`: a successful analysis always builds
  the map, a failed one only releases a build that waited. Analyze's estimate
  (`AnalysisEstimate`) includes the build's, so it is confirmed once.
- **Roles come from the strengths** (ADR 0024). The analysis recommends up to
  `ROLE_CANDIDATE_COUNT` candidate roles (20 until ADR 0029, 10 now); `assessment` hands them to `rolemap.replace_candidates`,
  and `rolemap.role_candidate` holds the latest set. A build matches them to
  the postings in scope locally (embeddings, plus title words) and keeps the
  first ten with openings; nothing clusters any more. With no candidates, a
  build places nothing. Fits are scored once per build, when
  `RoleMapBuildFinished` reaches the dispatcher, and every estimate that leads
  to a build includes them (`fits_cost_usd`). `GET /role-candidates` lists the
  candidates; since Phase 8 the role map no longer shows them.
- **Candidate roles are searched for** (ADR 0025). There is one ownerless
  `himalayas` crawl source per job title and place: a country, or "Remote"
  (`market.domain.search_scope`; a region adds none, ADR 0026). Only the title
  leaves the platform, and only the first page of each search is read. Remote
  work open worldwide is in scope for every listed location. An opening found
  there carries `credited_to` and is shown "via Himalayas" with its link.
  Since ADR 0027 a build asks for these searches itself (Phase 6).
- **Custom roles** (ADR 0021), gone since Phase 8: a pasted JD is now a
  posting of the user's own, aimed at from the Advisor (ADR 0030).
- **A Target is a role, plus an optional opening** (ADR 0022). `TargetRef` is
  `(role_id, job_posting_id?)`; plans and résumés store both columns. The
  fit is the role's, so resolving a Target spends nothing. Since ADR 0030 a
  Target can instead be a posting of the user's own (Phase 8). `/targets` and the private-JD
  scoring path are gone; `GET /matched-postings?role_id=` lists a role's
  openings.
- **Fill the gap** (ADR 0023). A new `advisor/gapfill` component
  (`gapplan | resume | activity → gapfill → target`, schema `gapfill`) writes
  questions per gap of the Target on the user's key, polled while `writing`.
  One submit checks the whole batch, records every answer through
  `profile.record_answers` as `user_answer` evidence, and emits
  `GapAnswersSubmitted`, for which the dispatcher queues nothing since ADR
  0035 (Phase 9): answering spends nothing. The old
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
    `market.request_sources(titles, places)` for every source it
    reads:
    - the candidates' searches in each searchable place;
    - the baseline boards.

    (Until ADR 0030 it also asked for its custom roles' companies' boards.)

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
    (On the build's `CandidatePlacement` since ADR 0031.)
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
- **The counts are settings** (ADR 0029). `ROLE_CANDIDATE_COUNT` (default 10,
  1–20) is how many roles an analysis recommends, every one searched for; the
  `skill_assessment` v3 prompt names it and the reply's schema enforces it.
  `ROLE_MAP_TOP_K` (default 10, at most the candidate count) is how many a
  build keeps by the local estimate, and only those k are named, analysed and
  fit-scored; they are the whole map since ADR 0030. They reach `RoleMapService(top_k,
  candidate_count)` and `AssessmentService(candidate_count)` through the
  factories; the selection rules take them as `limit` and `ceiling`.
  `RECOMMENDED_ROLE_COUNT` and `CANDIDATE_ROLE_COUNT` are gone, and the SPA
  says `max_roles`, never "ten".
- **The map and Top matched agree.** Reconciliation retires a role merged into
  another as well as one that went, and never retires one twice; migration
  0024 retired the merged-away roles earlier builds had left live. `GET /roles`
  answers from `rolemap.map_roles`, which counts each role's openings live
  against the current scope, as `matched_postings` lists them; an opening in
  two roles is listed under each.

## Phase 8 scope

The role map becomes the market's side only, and evaluating the user moves
out of it (`docs/plan.md`), one branch per step under `epic/no-ticket/phase-8`:

- **A posting of your own is a Target, not a role** (ADR 0030). "Aim at a
  posting of your own" in 04 Advisor (title, company, JD required) replaces
  "Add a role of your own" in 03 Roles.
  - **The Target.** `TargetRef` is `role_id` with an optional
    `job_posting_id`, or `private_job_posting_id` alone; `gapplan.plan`,
    `resume.resume` and `gapfill.question_set` keep exactly one, by check
    constraint. Routes take the three ids in bodies and query strings
    (`api.dependencies.TargetQuery`); the hash says `?posting=`.
  - **Its evaluation, in `target` since ADR 0033.** Since ADR 0034,
    `POST /own-postings/{id}/target` (priced by `/target-estimate`) records a
    `PostingEvaluation` run when the posting is set as the target, which
    `target.evaluate_own_posting` works through and the Advisor polls. The run reads `PostingRequirement`s
    (`rolemap.extract`) and the AI's `PostingRequirementFit` (`rolemap.fit`),
    then works out the fit (`OwnPostingFit`) locally with
    `get_posting_fit_result`: a posting's fit is never an AI call. No build reads or
    scores it; after a new analysis it is `is_stale`, and setting it as the
    target again re-runs the projection only then.
  - **What went.** `Role.origin`, `company_name` and `private_posting_id`,
    `/roles/custom`, `CustomRoleAdded`, `market.discover_board` and its
    probing, and `request_sources`'s company ids. Migration 0025 moved custom
    roles with a JD to postings of the user's own, re-pointed what was aimed
    at them, and retired every custom role.
- **A role candidate is only a query** (ADR 0031). `RoleCandidate` keeps
  `rank`, `title`, `description`, `dimension_keys` and `assessment_id`; no
  build writes to it. `recluster(owner_id, build_id)` records a
  `CandidatePlacement` per candidate it read (`rolemap.candidate_placement`,
  in `build_run.py`): `outcome` (`placed`, `outside_top_k`,
  `too_few_openings`), `role_id`, `opening_count`, `fit_estimate`, and the
  candidate's rank and title. `GET /role-candidates` answers unchanged from
  each candidate's newest placement; a build that found nothing in scope
  places nobody. Migration 0026 moved the outcomes off the candidates.
- **A fit is scored only when what it reads has changed** (Phase 8). A
  `RoleFit` and a `PostingRequirementFit` record `requirements_digest`
  (`get_requirements_digest`: the requirements scored, in order, and the fit
  prompt's version) beside `assessment_id`. `compute_fits` skips a role whose
  newest fit `is_current`, and a rescore of a posting of the user's own
  reuses its projection the same way, so a rebuild on an unchanged market and
  unchanged strengths spends nothing on fits. Estimates stay ceilings.
  Migration 0027 added the column; fits taken before it are scored once more.
- **A fit for every opening** (ADR 0032). The AI scores each role once; every
  opening's fit is worked out from it locally, never an AI call.
  `get_requirement_relevance` centres each requirement's embedding similarity
  to an opening on its mean over the role's openings, and `get_opening_fit`
  reweights the role's requirements by it (`OPENING_EMPHASIS`, a floor and a
  ceiling, in `constants.py`) and evaluates them with weighted gaps
  (`SkillGap.weight`, which `closing_lifts` honours). `compute_fits` stores
  them as `PostingFit`s with the opening's `role_id`,
  replaced per role by each build as a cache. `GET /matched-postings` ranks a
  role's openings by them (`fit_basis: "posting"`) for the Advisor; since
  ADR 0049 the role map lists them newest first, with no fit. A Target with an opening plans against `rolemap.opening_fit`
  (`RequirementBasis.OPENING`), or the role's fit before one exists.
- **A role's name is one job title.** `role_extraction` v2 tells the model to
  leave out where or how a role is worked, gender tags and company or team
  names, and to name one job rather than a group. `parse_role_name` takes a
  trailing work-arrangement or gender tag off every name a build stores, as a
  backstop; migration 0029 applied it to the names already stored.
- **The role map shows roles and openings only.** 03 Roles no longer lists
  the recommended roles that did not make the map, and does not call
  `GET /role-candidates`. Each opening names its company, then its posting,
  place, pay and any credit; the role it is in is the one selected, so no row
  names it (ADR 0049).

## Phase 9 scope

A posting of the user's own belongs to Target (ADR 0033), one branch per step
under `epic/no-ticket/own-posting-target`; the rest of the phase
(`docs/plan.md`) one branch per step under `epic/no-ticket/phase-9`:

- **Target owns it end to end.** The `target` schema holds
  `private_job_posting` (the JD, moved from `market_user`, ids kept),
  `posting_evaluation`, `posting_requirement`, `posting_requirement_fit` and
  `own_posting_fit`; the crawler has no grant on it. `target` has the full
  component layout (`domain/`, `infra/`, `factory.py`, `jobs.py`), the
  `/own-postings` routes live in `api/routes/target.py`, and the job is
  `target.evaluate_own_posting`.
- **The fit rules stay in `rolemap`, lent as a stateless kit.**
  `RoleMapService.strengths`, `extract_requirements`, `infer_requirements`,
  `project_requirements`, `estimate_requirements`,
  `estimate_inferred_requirements` and `estimate_projection`, and the pure
  `get_projection_digest` and `get_posting_fit_result`, store nothing.
  `rolemap.posting_fit` holds openings' fits only: no `basis`, `role_id`
  NOT NULL.
- **Uploaded or filled in** (ADR 0034). "Use your own role" (`#/advisor/own`)
  takes a PDF, Word or text file (`POST /own-postings/upload`, title
  optional), or a title, an optional company and optional requirements, one
  per line (`POST /own-postings`). Adding spends nothing and queues nothing.
  The file is stored in object storage and read by the worker, never in a
  request handler, with `kernel.documents` (shared with the résumé parser),
  under `OWN_POSTING_MAX_BYTES` / `OWN_POSTING_MAX_PAGES`; once read it
  becomes the JD and the file is deleted. Migration 0031 added `source`,
  `filename`, `content_type` and `storage_key`. Pasting a JD is gone.
- **Evaluated when set as the target** (ADR 0034). "Set as target" is priced
  by `GET /own-postings/{id}/target-estimate` (0 when the fit is current)
  and queued by `POST /own-postings/{id}/target`, which replaced `/rescore`;
  the SPA then opens Fill the gap. A role filled in with nothing listed
  (`has_estimated_requirements`) has its requirements estimated from its
  title (`rolemap.infer_requirements`, template `typical_requirements`); an
  upload with no title (`has_placeholder_title`) takes the name the
  extraction reads. Migration 0032 added both flags and `source = 'filled_in'`.
- **`market` has no pasted JDs.** `PrivateJobPosting`, the paste methods and
  `GET /job-descriptions` are gone. Migration 0030 moved the data; 0015, 0025
  and 0028 are guarded so a fresh database still builds.
- **Regenerated only when asked** (ADR 0035). Submitting answers in Fill the
  gap spends nothing and queues nothing. A gap plan and a résumé record what
  they were drafted from — `profile_version` and `target_digest`
  (`target.get_target_digest`, a `DraftBasis`; migration 0033) — and
  `TargetService.get_outdated_reasons` tells the latest ready one it is
  outdated by `evidence`, `target` or both (`is_outdated`, `outdated_by`). The
  Advisor shows a banner with Regenerate, priced first: a plan's next version
  through `POST /gap-plans`, a résumé's through
  `POST /tailored-resumes/{id}/regenerate`. A manual edit keeps the basis.
- **A plan cites what you answered** (ADR 0036). `gapfill.get_answers` lists
  each answered question's evidence under its gap; `gap_plan` v2 shows them
  beside their gaps ("answered in [E2]"), and an uncovered requirement may
  cite its own answers and nothing else, which `assert_draft_valid` checks
  (`answers_by_gap`). `gapplan`'s factory takes the `GapFillService`.
- **Each fact with its date** (ADR 0037). `profile.get_evidence_line` is the
  one way a prompt shows a fact: `[E3] (github, 2026-08-14) …`, with
  `latest …` for a tally, `from a résumé uploaded …` for a résumé line (its
  file's upload, `EvidenceView.stated_on`), `answered …` or `undated`
  (`get_date_label`). The snapshot is newest first, undated last. Every prompt
  that reads evidence has rules on time — `skill_assessment` v4, `gap_plan` v3,
  `gap_questions` v2, `resume_write` and `resume_revise` v2: the newer fact
  wins, and a stated date never makes the work recent.
- **Export what you previewed** (ADR 0038). A template's spec and the page
  constants in `resume/domain` are the one look: `render_html` reads them and
  `GET /resume-templates` serves them to the preview, which is laid out as the
  A4 page in points and trims what the PDF trims. The worker image carries
  Caprasimo and Figtree (`backend/assets/fonts`, fontconfig). A ready export's
  link is signed as an attachment ("<name> — <role>.pdf") and the SPA
  downloads it at once; an export records its `trim` (migration 0034), and an
  unchanged one is reused.
- **Sections you choose** (ADR 0039). `ResumeContent` is a header and
  `sections` (`resume/domain/section.py`: `SectionKind`, one shape each —
  text, entries, list, bullets); Experience always, every other kind once, up
  to three custom ones. `Resume.section_plan` is what each version is written
  to, and every saved version sets it. The Sections panel moves and removes
  sections as edits to the draft, saved as a version on request (Phase 11); adding one is priced
  (`/sections/estimate`), sets the résumé `filling`, and `resume.fill_section`
  writes that section only (`resume_section` v1). `resume_write` and
  `resume_revise` are v3. Migration 0035 moved stored content into sections.
- **Templates of your own** (ADR 0040). A template is a `TemplateSpec`
  (`resume/domain/template_spec.py`): layout, two fonts from `TEMPLATE_FONTS`,
  four `#rrggbb` colours (name and text at least 4.5:1 on white), sizes in
  their ranges, sidebar list kinds, heading case and bullet; never markup.
  Organic and Plain are `BUILT_IN_TEMPLATES`. `CustomTemplate`
  (`resume.custom_template`, RLS) keeps a user's own, up to
  `RESUME_TEMPLATE_MAX`; a résumé holds a built-in `template` or a
  `custom_template_id`, exactly one (`ck_resume_look`), and the wire carries
  either as one template id. `POST`/`PUT`/`DELETE /resume-templates` keep
  them, `GET /resume-templates/limits` feeds the editor, and deleting one
  moves its résumés to Organic. An export stores the `spec` it rendered and
  reuse compares specs. The preview draws every layout; the SPA hosts DejaVu
  Serif and Mono subsets. Migration 0036.
- **A template from a file** (ADR 0041). "Start from a file" posts a PDF to
  `POST /resume-templates/upload` (under `TEMPLATE_UPLOAD_MAX_BYTES` /
  `_PAGES`); a `TemplateReading` (`resume.template_reading`, RLS) is polled at
  `GET /resume-template-readings/{id}` while `resume.read_template` (queue
  `docs`) walks the first page with pypdf (`infra/style_reader.py`) into
  `StyleRun`s, with no text in them, and `get_template_spec_from_runs` makes
  the draft, listing which values were read and which took Organic's. The file
  is deleted once read or failed (`unreadable_file`); nothing of its text, name
  or fonts is stored, and `resume.forget_template_reading` deletes the run a
  day on. Saving it is ADR 0040's `POST /resume-templates`. Migration 0037.
- **Advisor jobs in the background** (ADR 0042). Questions, a plan, a résumé
  or a section, and scoring a posting of the user's own record `stage`,
  `progress` and `estimated_cost_usd` on their rows (migration 0038);
  `AiGateway.run(on_progress=)` streams the reply and reports its share of
  `expected_output_tokens`, capped at 95% (`kernel.progress`). `POST
  .../cancel` marks a running job `cancelled`; it stops before its next call,
  mid-stream, or before its save (`JobCancelledError`), and a cancelled
  version is never shown. One job of a kind per Target at a time. `GET
  /activity` gathers every component's `running_jobs` as `advisor_jobs`; the
  SPA shows `AdvisorJobCard` on the job's tab, a spinner on the step tabs and
  `AdvisorJobNotice` in the corner. "Target this role" prices and starts the
  questions; "Set as target" queues them after scoring
  (`wiring.queue.queue_questions`).
- **The Advisor as prototyped** (no ADR). Evidence is collapsed everywhere
  (`EvidenceDisclosure`: "Show evidence (n)", "Evidence ▾"). Each gap of a
  plan has a bar of its fit points out of `lift_scale` (10, or the plan's
  largest lift), and the plan's header names the `answer_count` its draft
  read. The Résumé had three columns until Phase 11, which made it two (see
  there); "Regenerate résumé" with its last-generated line is on the
  Write-for card.

## Phase 10 scope

A tailored résumé is written from the user's sources, whether or not they
uploaded one (`docs/plan.md`), one branch per step under
`epic/no-ticket/phase-10`:

- **Every section, written at once from the sources** (ADR 0043). A résumé
  holds every built-in kind (`DEFAULT_PLAN`, `get_full_plan`), each with
  `is_shown` on its `Section` and its `SectionSlot` (which compares without
  it). Summary, experience and skills start shown (`DEFAULT_SHOWN`), the rest
  hidden; Experience is always shown, and `MAX_SECTIONS` limits only what is
  shown. Generate writes them all (`resume_write` v4, given the connected
  accounts as `ProfileSnapshot.accounts`): without a timeline or an uploaded
  résumé, Experience is one entry per place the work was done, never an
  invented title, and repositories split into experience, open source and
  side projects. Show and Hide are free edits (since Phase 11 kept in the draft until the user saves the version); only shown
  sections print (`ResumeContent.get_shown`). `resume_revise` v4 keeps a
  section's state unless asked (`get_proposal_layout`). "Fill from your
  sources" (`POST /tailored-resumes/{id}/sections`, priced) fills an empty
  section or a new one of the user's own. Migration 0039.
- **A résumé cites what you answered** (ADR 0044). `ResumeService` reads
  `gapfill.get_answers`; each coverage row carries the answers to its gap
  (`dim:` or `req:` key, `target.gap_key_for_*`), stored on the résumé and
  listed in the prompts as "answered in [E41]". `resume_write` and
  `resume_revise` are v5: a gap may be claimed only from its own answers.
  Every write, proposal and filled section runs `get_claims_settled`, which
  drops a claim (`answers`) that names no requirement or a gap its citations
  do not rest on alone, keeping the line (ADR 0046). The verdict stays a gap;
  the requirements panel says "Answered by you".
- **Record the career timeline** (ADR 0045). `skill_assessment` v5 reports
  the `positions` résumé lines and answers state, and is no longer given the
  stored timeline. They are checked (`profile.assert_position_readings_valid`:
  cites only `resume` or `user_answer` evidence, dated in the past) before
  anything is stored, then `ProfileService.replace_positions` replaces the
  timeline with them, citing `evidence_ids` and the `skill_assessment_id`.
  No profile version moves. Migration 0040.
- **Found while testing Phase 10.** The left column takes a share of a wide
  screen and the layout stacks below 1240px. Headline, contact, section
  headings (a built-in section may take its own `title`, kept through
  `get_headings_kept`), entry fields and list items are edited in place. A
  résumé may set its own `heading_font` and `body_font` over its template's
  (ADR 0047, `get_spec_with_fonts`, migration 0041), from the Template panel.
  Contact details are typed `ContactItem`s (ADR 0048, migration 0042), read
  from the model's line by `get_contact_items` and drawn with the inline SVG
  icons in `CONTACT_ICONS`, which `GET /resume-templates/limits` also serves.

## Phase 11 scope

The 4 October prototype (`docs/plan.md`), one branch per step under
`epic/no-ticket/update-prototype`:

- **CareerPolaris.** The app's name, with `components/AppIcon` (four colour
  versions) in the sidebar and on sign-in, and `web/public/icon.svg` as the
  favicon. Internal names followed in ADR 0056.
- **Openings for this role** (ADR 0049). The role map lists the selected
  role's openings newest first (`GET /matched-postings?order=newest`,
  `posted_on`), ten at a time with "See all n openings", and no fit per
  opening. No row selects an opening: "Target this role" aims at the role.
  Opening fits (ADR 0032) are still computed for Targets that name one.
- **No target until one is chosen** (ADR 0050). The current Target and its
  history live in `localStorage` per account (`features/advisorTarget.ts`),
  written by "Target this role", "Set as target", "Use again" and every
  Advisor visit. Entering the Advisor from elsewhere opens the stored Target
  (`getArrivalFocus`), never the role map's selection, or `AdvisorNoTarget`
  (steps locked, three ways in). "Previous targets" on the banner
  (`PreviousTargets`) joins that history with `/gap-plans` and
  `/tailored-resumes`; switching only navigates. No backend change.
- **The Résumé in two columns** (no ADR). The tools on the left as three
  collapsible cards — Layout (template, fonts, options, Sections; open),
  Revise with AI (open) and Coverage (the requirements; closed) — and the page
  on the right, with "Save as vN" and Export as PDF beneath it; stacked page
  first below 1240px. Saved résumés became the Version list on the Write-for
  card, one entry per saved résumé; another target's goes through
  `onRevisit`. Older versions of one résumé are not listed: a version carries
  no content to read back.
- **More fonts.** `TEMPLATE_FONTS` is ten families: the four before, plus
  Inter, Lato, Source Serif 4, Merriweather, EB Garamond and IBM Plex Mono,
  each a Latin 400/700 subset hosted by the SPA and installed in the worker
  image. Migration 0043 widens the résumé's font checks; `test_fonts.py`
  checks fontconfig finds each by name.
- **Remove one entry.** Each entry on the résumé page has a round × in the
  page margin left of its title (`resume-remove-entry`), so the title stays
  where the PDF prints it; it drops the entry from the draft; saving the
  version keeps the change. A section may be left with no entries.
- **Sections saved on request.** Show, Hide, moving and removing a section in
  the Sections panel change the draft only, like any edit on the page;
  "Save as vN" keeps them. Filling a section is refused while there are
  unsaved changes, because it is written into the saved version.
- **Undo.** Every edit to the résumé draft goes through `editDraft`, which
  keeps the drafts before it (`getStackWith`, at most 50); "↶ Undo" and
  Cmd/Ctrl+Z (outside a field being typed in) step back. Saving or opening
  another résumé clears it.

## Phase 12 scope

Hybrid deployment (`docs/plan.md`), one branch per step under
`epic/no-ticket/hybrid-deploy`; `docs/deploy.md` is the runbook:

- **Two places** (ADR 0051; since ADR 0062 the machines
  `droplet-1vcpu-2gb` and `compute-m5pro-48gb` in `deploy/`, not profiles). A
  DigitalOcean droplet (1 vCPU, 2 GB) runs Caddy, `web`, `api` and Postgres,
  about 1 GB. The operator's machine runs the worker and the crawler, which
  hold the embedding model. They meet through Tailscale (`scripts/tunnel-up.sh`
  forwards only 5432 to Postgres on loopback; the compute side dials out). Files
  are in Spaces; the S3 gateway runs only on `local` and `ci`. Every published
  port binds to `127.0.0.1`, because Docker goes around `ufw`; infra restarts
  with its host; Postgres's memory is set in each machine's infra file.
  Both places migrate under an advisory lock (`cli.migrate.migration_lock`),
  and an image older than the schema refuses (`SchemaAheadError`). Found on
  the way: a fresh database could not migrate past 0013.
- **Work waits for the compute machine** (ADR 0052). The worker and the
  crawler beat into `presence.process` (`kernel.presence`, a thread with its
  own connection; migration 0044), every `PRESENCE_HEARTBEAT_SECONDS`.
  `Staleness.is_stale(…, online_since=)` counts only the time the worker has
  been up; `BuildRun.is_market_wait_over` only the crawler's. `GET /activity`
  carries `processing`; `CostConfirm` says "Processing is offline; this
  starts when it is back", the running bar leads with the machine, and the
  shell asks every 30 s while it is away. The DSN helper is
  `kernel.db.get_psycopg_dsn`.
- **Caddy at the edge** (ADR 0053). `proxy/` builds Caddy 2.11.6 with
  `caddy-ratelimit` (pinned by commit), non-root, read-only, no capabilities
  (the unprivileged-port sysctl opens 80/443). One origin for
  `SITE_HOSTNAME` (`<ip>.sslip.io` until there is a domain): `/api/*` to the
  api, the rest to `web`. `EDGE_MAX_BODY_SIZE` (413), header/body/idle
  timeouts, and per address `EDGE_AUTH_REQUESTS_PER_MINUTE` on `/api/v1/auth/*`
  and `EDGE_REQUESTS_PER_MINUTE` on everything (429, `Retry-After`). No API
  gateway. `make lint` validates the Caddyfile. `ObjectStore.ensure_bucket`
  asks `HeadBucket`, because a Spaces key scoped to one bucket may not list.
  `make backup-db` / `restore-db` move `pg_dump` through a second bucket
  (`BACKUP_S3_*`) with the pinned AWS CLI image.
- **Limits per account and address** (ADR 0054). `kernel.limits.Limiter`
  counts a fixed window per limit and subject in `limits.counter` (a digest,
  never the address; migration 0045), in a transaction of its own;
  `wiring.limits` names `signups` (per address, `SIGNUPS_PER_ADDRESS_PER_DAY`),
  `uploads` (per account, `UPLOADS_PER_ACCOUNT_PER_DAY`: résumés, own
  postings, template PDFs) and `syncs` (`SYNCS_PER_ACCOUNT_PER_HOUR`). A
  refusal is `RateLimitedError(retry_after_seconds=)`, answered 429 with
  `Retry-After`. uvicorn believes `X-Forwarded-For` only from
  `FORWARDED_ALLOW_IPS` (careerpolaris_net's subnet on the droplet). The SPA words the
  proxy's own 429 and 413 and reads error pages that are not JSON.
- **Releases by digest** (ADR 0055). CI runs on pushes to `master` (it named
  `main`/`develop` before and never ran there) and pull requests. A version
  tag (`v1.2.3`) on a commit already on `master` — `make release BUMP=patch|minor|major`
  makes and pushes the next one, idempotently — runs the gates and then
  `make push-app` (ADR 0060), which refuses any other ref: the prod images for
  `RELEASE_PLATFORMS` (amd64 and arm64, the latter under QEMU) to
  `RELEASE_REGISTRY`, tagged with the version, and `release.env` naming each
  by digest, attached to the tag's GitHub Release. Each place runs
  `make pull-app RELEASE=release.env`, edge first. `pull_policy: never` stays.

- **Local S3 without MinIO** (ADR 0058). MinIO no longer publishes pullable
  images, so `local` and `ci` run the Versity S3 Gateway (`versity/versitygw`), with
  objects as plain files in the `objectfiles` volume and no console. The
  integration tier ensures the bucket once per session
  (`tests/integration/conftest.py`), because only the api creates it.

Not yet: a domain (and with it Google sign-in and Cloudflare in front), and an
arm64 image that the gates themselves ran against.

## The rename (ADR 0056)

Everything inside is CareerPolaris, on `chore/no-ticket/rename-to-careerpolaris`
in `epic/no-ticket/hybrid-deploy`: images `careerpolaris-{backend,web,proxy}`,
network `careerpolaris_net`, compose projects `careerpolaris-infra` and
`careerpolaris-app`, cookies `careerpolaris_refresh` and
`careerpolaris_google_attempt`, the font directory, `SERVICE_NAME`, token
issuer and audience `careerpolaris` / `careerpolaris-api`, the user agent
`CareerPolarisBot/1.0`, the package names, the release file's
`CAREERPOLARIS_*_IMAGE` and CI's database and bucket. Everyone is signed out
once, by the cookie and the issuer. Old volumes are copied once by hand
(ADR 0056); the repo keeps no command for it. Accepted ADRs, past phases in `docs/plan.md` and the
excalidraw drawings keep the names they were written with.

## Deployment shape per machine (ADR 0062)

On `epic/no-ticket/deploy-layout`, one branch per step: `infra/`'s scripts
moved to `scripts/`; what runs on a machine, how big it is and under which names
moved out of `.env` into `deploy/<machine>/` (see Running it); `.machine` names
a checkout's machine; `MODE`, `COMPOSE_PROFILES`, `compose.yaml`,
`compose.dev.yaml`, `infra/compose.yml` and the droplet's env template are
gone. `local` and `ci` take `-local` and `-ci` names, so a development clone
runs beside production on the compute machine, and every start, stop or
destructive target refuses a stack another checkout started. The droplet and
compute kept their names, so their volumes carried over; each place writes
`.machine` and deletes the moved keys from `.env` once (`docs/deploy.md`,
section 6). ADR 0057 is superseded.


## Phase 13 scope

AI on the platform's key, under a quota (`docs/plan.md`), one branch per step
under `epic/no-ticket/platform-ai`:

- **Count what a call really costs** (no ADR). Every call is recorded with
  the provider's own token counts: `Provider.stream` yields `TextDelta`s and
  a `Usage` (Anthropic's `message_start`/`message_delta`, OpenAI's
  `include_usage` chunk, Google's `usageMetadata`), and `GuardedClient.stream`
  reads the body as it arrives, under the size limit, closing the connection
  when a job is cancelled or a chat reader leaves. A call is priced at the
  rate of the model asked for, and `pricing.rate_for` reads a dated snapshot
  id (`…-20251001`) as the model it names. `estimate_tokens` counts Chinese,
  Japanese and Korean near a token a character (`token_counting` in
  `pricing.json`); `estimate_ceiling` prices every attempt at its output
  limit (`Estimate.ceiling_cost_usd`). The ledger keeps each row's
  `estimated_input_tokens` and `estimated_cost_usd` beside what it used, and
  `is_estimated` when the counts are ours (migration 0047).
- **Record who paid for a call** (ADR 0064). A call runs on the user's own
  key or the platform's (`kernel.ai_gateway.Funding`). `CredentialStore.load`
  returns the user's credential or a `PlatformCredential`, and the gateway
  takes the platform's provider, model and key from `PLATFORM_AI_*` (blank
  key: off; a model with no published rate refuses to start). The
  platform's key failing answers `ai_platform_unavailable` (503) and leaves
  the user's credential and jobs alone. Every ledger row records `funding`
  (migration 0048), and the user's monthly cap counts only `own`.
