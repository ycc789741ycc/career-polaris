# Phase 1
## Login
* User create account in the system — **done as own email + password**, no
  external provider. Address verification and password reset are not built
  yet: both need email delivery, which is still undecided.

## Sources Connector
* Jira
* Github
* User upload resume

## LLM Configuration
* Able to setup and connect under user account

## Job Platform for Role Map Analysis
**Changed during implementation.** Glassdoor, Indeed and LinkedIn cannot be
crawled — their terms forbid it, and LinkedIn has litigated it
(`domain_model.md` decision 6). Replaced by sources that permit it:

* Public ATS job boards: Greenhouse, Lever, Ashby — driven by the companies a
  user watches
* Career pages carrying schema.org `JobPosting` JSON-LD
* JDs the user pastes, which stay private to them
* A company with none of the above gets `manual` coverage: it says plainly that
  nothing updates automatically, and offers "paste a JD" instead

LinkedIn remains a *profile* connector (the user's own data, via OAuth) in a
later phase — never a market data source.

## Role Map
## Assessment

# Phase 2
## Gap Plan
* **Done.** Plan a route to a Target: one of the top matched openings, a role
  you watch, or a JD you paste ("My own JD"). The Target's requirements are
  frozen into the plan, so it survives the posting expiring or the role
  re-clustering (domain decision 16, ADR 0005).
* The gaps are ranked by the fit points each is worth — the fit's own
  arithmetic, not the model's opinion. Requirements with no evidence at all
  come first on a tie. The model explains each gap, citing the user's
  evidence, and drafts milestones, tasks and projects; a draft that invents
  evidence or skips a gap is rejected.
* Drafting runs on the user's key after a cost estimate, as a job the page
  polls; a failure says why (ADR 0006).
* Regenerating adds a version and carries finished tasks over; a task done in
  one plan counts in every plan where a matching task closes the same gap.
  Plan history lists each Target's latest version.
* Stepping stones: up to three roles the user already fits better.
* Not yet: suggesting a successor Target when its role splits or merges —
  rolemap does not emit that event yet.

## Resume Advisor
* **Done.** Write for a Target — a top matched opening, a watched role, or a
  pasted JD ("My own JD", scored on the user's key first). Filters are by where
  an opening was found (ATS board, careers page, public job API, watchlist),
  never LinkedIn, Indeed or Glassdoor.
* The first version is written from the user's evidence, revising their
  uploaded résumé when there is one. Every line the model writes cites the
  evidence behind it — the grey note under each line — and a draft that cites
  nothing, or evidence the user does not own, is rejected.
* "Their requirements → your evidence": covered, partial or gap for each
  requirement, decided by the user's scores against the Target's bar, not by
  the model.
* Edit any line in place; "Save this version" keeps a new version, and a line
  the user rewrote is marked as theirs. Saved résumés list every Target
  written for, and reopen at their latest version.
* "Revise with {model}": a chat that streams its answer and proposes a
  revision, applied as a new version only when the user says so.
* Three templates (Warm, Plain, Brief) and export to a white PDF with a
  short-lived download link (ADR 0007).
* Not yet: the interview-report prompt two weeks after tailoring.

# Phase 3
## Support OAuth login
* **Done.** Google — our own OpenID Connect code exchange (PKCE, state, nonce)
  in `identity`, which ends by issuing *our* session: the same access token and
  rotating refresh cookie as a password sign-in (ADR 0008).
* A Google address is verified, so an existing password account at the same
  address is linked, and its password and sessions are removed — our own
  addresses never were verified, so whoever registered one first must not keep
  a way in.
* Optional per deployment: blank `GOOGLE_OAUTH_CLIENT_ID` and the sign-in
  screen offers email and password only.
* Not yet: unlinking Google, or linking it from Settings.

# Phase 4
## Evidence insight
* **Evidence shape — done.** Every fact says whether it is one piece of work
  (`item`) or a tally over many (`summary`), so nothing that counts work counts
  a tally as one more. Jira issues carry the date they were resolved, or last
  updated while open.
* A timeline of when the work happened was built and then dropped: it is not
  on the Sources page.
* **Source mix — done.** "What it found so far" is one stacked bar of facts by
  source, with counts and whole percents that add up to 100. The note under it
  says the bar shares out facts, not effort.
* **Where the work lives — done.** One bar per GitHub repository (commits,
  ADR 0016) and per Jira epic (issues, ADR 0017), each source on its own scale.
  Bars come from the connectors' own tallies, now stored as numbers (`tally`),
  not from the few items a sync keeps. Every fact names its repository or epic
  (`subject`), so clicking a bar lists the tally and its items.
* **What backs a score — done.** The evidence table has a "Cited by" column
  from the latest analysis, a count of how many facts back a score, a filter
  for the ones none cite, and a note when sources changed after the analysis.
  The strength report already lists the facts behind each score.

# Phase 5
## v3 journey redesign
The v3 domain diagram (`docs/job_searching_advisor_domain_concepts_v3.excalidraw`)
and the redesigned prototype (`prototype/`) change the journey. `domain_model.md`
(decisions 21–28) and `architecture.md` (T17–T23) describe where it ends up;
this is the order the code gets there.

Every step is its own branch cut from `master` and its own PR:
* tests for the new behaviour in the right tier, and `make lint`,
  `make typecheck`, `make test-unit` and `make test-integration` passing, with
  nothing skipped
* its ADR, and the `docs/decisions/README.md` index updated with it
* `CLAUDE.md`, and its row of the "What it does" table in `README.md`, updated
  to say what is now built

ADR numbers below are the next free ones at the time of writing. A step takes
whatever is next when it merges.

1. **Docs — done.** The v3 diagram, the prototype screens, the domain model,
   the architecture and this phase.

2. **Target locations — done.** `feature/no-ticket/target-locations`
   * 1–3 target locations, as a `market` domain rule next to
     `MarketPreference.chosen()`, checked again by the API schema. Served as
     `/target-locations`; the table stays `market_user.market_preference`.
   * Built as: `PUT /target-locations` saves the whole set, and a change emits
     `TargetLocationsChanged`, which rebuilds a role map the user already has
     (ADR 0018 gating). `GET /market-scope` gives the posting count. No ADR:
     architecture T17 records the decision.
   * Not yet: public-API crawl sources per location. There is no public job
     API adapter to materialise them for.
   * The "Where you want to work" panel moves from `Roles.tsx` to 01 Sources
     (`features/Connect.tsx`). The role map drops the market filter pills and
     the band toggle, and says how many postings are in the chosen locations.
   * README row: Profile & evidence.

3. **Remove the watchlist — done.** `refactor/no-ticket/drop-role-subscriptions`,
   ADR 0019
   * Built as: migration 0013 also drops `market_user.manual_refresh_log`, and
     the `CRAWL_MANUAL_REFRESH_PER_DAY` setting goes. `materialize_crawl_sources`
     is gone whole, since subscriptions were its only input; `discover_board`
     takes a company and no owner.
   * Delete `CompanySubscription`, `SubscriptionAdded`, the
     `/role-subscriptions` routes, `refresh_company`, and the subscription
     input to `materialize_crawl_sources`. Keep board discovery
     (`market/crawling/discovery.py`, `discover_board`), which step 5 drives.
   * Remove the `subscription` Target kind, `MatchedPostingView.subscription_id`,
     and the SPA's watch form, Subscribe toggle and "subscribed" chip.
   * Migration: drop `market_user.company_subscription` and its `fanout_read`
     policy, then drop `subscription_id` from `gapplan.plan` and
     `resume.resume`. Rows aimed at a subscription are deleted first, and the
     migration says how many.
   * README row: Gap plan (no watched roles).

4. **Ten roles, built after each analysis — done.** `refactor/no-ticket/fixed-ten-roles`,
   ADR 0020, superseding ADR 0003
   * Built as: `activity.build_after_analysis` decides what `AnalysisFinished`
     queues, migration 0014 drops the table, and the role map keeps a priced
     "Rebuild role map" button.
   * `rolemap/domain/selection.py` replaces the 3–20 bound with a constant of
     ten. Drop `RoleMapSetting`, `rolemap.role_map_setting`, `RoleCountChanged`,
     `/roles/settings`, `role_count` on the cost estimate, and the SPA's
     count input.
   * `AnalysisFinished` → `activity` requests a build for every successful
     analysis, reusing ADR 0018's gating. The Analyze cost estimate adds the
     build's, so there is one confirmation.
   * README row: Role map.

5. **Custom roles — done.** `feature/no-ticket/custom-roles`, ADR 0021
   * Built as: the route that adds a role records its build (as the rebuild
     route does), and the dispatcher only sends the company to board discovery.
     `POST /job-descriptions` is removed, and pasted JDs leave clustering.
     Until step 6, a custom role with a JD aims the Advisor through that JD.
   * `Role.origin` (`recommended` | `custom`). Reconciliation never retires a
     custom role, and custom roles do not count toward the ten.
   * `POST /roles/custom {title, company?, job_description?}` and a delete. The
     JD is stored through `MarketService.paste_job_description`. A company
     goes to board discovery as an ownerless `demand` source
     (`CustomRoleAdded`).
   * The role-map job matches in-scope postings by title words (and company).
     Requirements come from the JD when there is one, else from the matches.
     The cost estimate comes before "Add to Role Map".
   * The SPA's "Add a role of your own" form replaces `OwnJd.tsx`, and
     `charts/RoleMap.tsx` draws custom roles green, labelled "yours".
   * Pasted JDs already stored become custom roles, titled from the JD.
   * README row: Role map.

6. **A Target is a role, plus an optional opening — done.** `refactor/no-ticket/role-targets`,
   ADR 0022, amending ADR 0005
   * Built as: an opening narrows the title, company and fit, but a single
     posting's own requirements are not read yet — the role's are used (ADR
     0022 records the deviation). Picking a "Top matched openings" row
     selects the opening; `GET /matched-postings?role_id=` lists a role's.
   * `TargetRef{role_id, job_posting_id?}` in `target/domain/snapshot.py`.
     `RequirementBasis` becomes posting, then private JD, then role.
     `TargetService.options()` goes: the role map is the only picker.
   * Migrate `gapplan.plan` and `resume.resume` to `role_id` + nullable
     `job_posting_id`. Plans and résumés aimed at a pasted JD point at the
     custom role step 5 made from it.
   * The Advisor: a "Your target role" banner with "Change role", no
     `TargetChips`, and only `?role=` (plus the opening) in the hash —
     `?jd=` goes from `shell/navigation.ts`. Plan history and saved résumés
     are listed by role and company.
   * README rows: Gap plan, and "Resume Advisor" becomes "Résumé".

7. **Fill the gap — done.** `feature/no-ticket/gap-fill`, ADR 0023, superseding
   ADR 0012
   * Built as: up to four gaps asked about, 1–3 questions each; a résumé
     regenerated after answers is saved as an `answers` version. Not yet: the
     plan's provenance line ("uses your 4 answers"), and `activity` gating
     questions on the Target's fit.
   * A new `advisor/gapfill` component (domain, service, infra, factory,
     jobs), its `gapfill` schema with RLS, routes and schemas, a
     public-surface contract in `backend/.importlinter`, and the layering
     contract updated to `gapplan | resume | activity → gapfill → target`.
   * Questions per gap, from the Target snapshot's `DimensionGap` /
     `UncoveredGap`: "asked because", answer type and choices, fit points. A
     job on the `ai` queue with a status the page polls (ADR 0006).
   * One submit: the whole batch validated, each answer recorded through
     `profile.record_answer` in one transaction, then `GapAnswersSubmitted`,
     which the dispatcher turns into `gapplan` and `resume` regenerate jobs
     for that Target.
   * `EvidenceSource.SELF_REPORTED` becomes `USER_ANSWER` ("Your answers"),
     with a data migration.
   * Remove the old questions: `FollowUpQuestion`, `QuestionRound`,
     `generate_questions`, `/questions`, the `ProfileUpdated` branch in
     `worker/dispatcher.py`, the `assessment.follow_up_question` and
     `assessment.question_round` tables, and `FollowUpQuestions.tsx` on
     Sources.
   * The Advisor opens on `#/advisor/gaps`: "First: Fill the gap → Then,
     either: Gap plan | Résumé".
   * README row: Profile & evidence (answers), and a Fill the gap row.

8. **Profile confidence on Strengths — done.** `feature/no-ticket/profile-confidence`
   * Built as: `assessment.domain.profile_confidence` (the unweighted mean),
     `profile_confidence` on the strength report, and migration 0018 renaming
     `warm` to `organic` and moving `brief` résumés to `plain`. The AI & model
     screen's list says questions are written per gap of the target role, not
     for uncertain scores (domain 2.12).
   * `assessment` returns profile confidence with the strength report. Today
     `App.tsx` averages it in the SPA.
   * Strengths shows it next to Re-analyse, and lists dimensions least
     certain first. The sidebar loses its meter (`shell/Sidebar.tsx`,
     `ShellContext`).
   * Copy from the prototype: "What runs on your key" on the AI & model
     screen, and the Organic and Plain résumé templates.
   * README: the Strength report row, and removing the "redesign under way"
     line.

Order: step 3 before 6, step 4 before 5, and steps 5 and 6 before 7. Step 2
and step 8 can land any time.

9. **Roles from the strength assessment — done.** `feature/no-ticket/roles-from-strengths`
   (ADR 0024, domain decision 29; the v3 diagram's 2d–2h as drawn)
   * `skill_assessment` v2 also recommends up to 20 candidate roles, each
     resting on dimensions from the same reply. `assessment` hands them to
     `rolemap.replace_candidates`; they live in `rolemap.role_candidate`
     (migration 0019).
   * A build embeds the candidates, gives each posting in scope to the nearest
     one (or one whose title it names), and keeps the first ten with three or
     more openings. Naming, requirements, lineage and free unchanged roles
     work as before. With no candidates, only custom roles are placed.
   * Per-user HDBSCAN clustering, `rank_by_fit` and the direct
     `scikit-learn` dependency are gone; `rolemap` no longer reads `profile`.
   * Fits are scored once per build, on `RoleMapBuildFinished`, and every
     estimate that leads to a build prices them (`fits_cost_usd`).
   * The role map lists the recommended roles the market lacks
     (`GET /role-candidates`).

10. **Search a public job API for the candidate roles — done.**
    `feature/no-ticket/himalayas-candidate-search` (ADR 0025, domain decision 30)
    * `RoleCandidatesReplaced` and `TargetLocationsChanged` queue
      `market.request_searches(titles, locations)`: one ownerless `himalayas`
      crawl source per title and place, for a country or "Remote"
      (`market.domain.search_scope`). Migration 0020 adds `last_requested_at`.
    * A Himalayas adapter reads the first page of each search. The crawler
      looks for unfetched sources every two minutes, announces a changed place
      once per crawl, and retires searches nobody has asked for in eight weeks.
    * Remote work open worldwide is in scope for every searchable location.
    * Openings found there say "via Himalayas" and link back (`credited_to`).
    * On-site Taiwan and Singapore: Appier, OKX and Stripe join the baseline.
    * Not solved: the same opening from a company board and from Himalayas is
      two postings.

# Phase 6
Every role-map build spends the user's own key: naming the roles, then
scoring the fits. So the map is built only when the user asks for it, and
the market data it is built from is fetched then, for what that build needs,
not on a timer. Two branches, in this order:

1. "Choose target locations from a list": every place a user picks is one
   the platform knows how to search, or plainly can't.
2. "Fetch the market and build the role map only on demand": the weekly
   crawl, market-driven rebuilds and the fan-out to users go; a build waits
   for the sources it needs that aren't fresh.

Both have the same definition of done as Phase 5: tests in the right tier,
every gate passing with nothing skipped, an ADR each with the index, and
`CLAUDE.md`, `README.md` and `docs/architecture.md` saying what is built.

## Choose target locations from a list
"Where you want to work" in 01 Sources is a free-text box today. Whatever the
user types is matched against posting locations word by word, and only a
country or "Remote" gets a search (ADR 0025). A city, a region or a typo
silently gets none, and nothing on the screen says so.

The box becomes a choose list of three kinds of place, each with a known way
to be matched and, where it can be, searched:

| Kind | Example | Matched by | Searched |
|---|---|---|---|
| Remote | "Remote" | remote work open to anyone | Himalayas, `worldwide` |
| Country | "Taiwan" | the country's names and main cities | Himalayas, by country code |
| Region | "Europe" | any member country's names and cities | no search of its own |

Its own branch, `feature/<ticket>/location-choice-list`, cut from mainline.
It lands before "Fetch the market and build the role map only on demand",
which relies on every place being either searched or plainly not. Same definition
of done as Phase 5, with its own ADR: it closes `PUT /target-locations` to a
fixed set, changes domain decision 21, and amends ADR 0025's "a region adds no
source" from a gap into a rule.

1. **The options come from the one place table.**
   * They are "Remote" (remote work open to anyone), then the regions, then
     one entry per country in `market.domain.search`'s table, under its
     canonical name ("United Kingdom", not "UK"), each group A to Z.
   * A region is a named set of the table's countries: Europe, Asia-Pacific,
     North America and Latin America to start with. A country may sit in
     more than one region, and every country belongs to at least one.
   * `market.target_location_options()` returns each option with its kind,
     and `GET /target-location-options` serves them as a page (ADR 0014). The
     SPA never keeps its own copy, so adding a country or a region to the
     table adds it to the list.

2. **Only listed places are accepted.**
   * `chosen_target_locations` rejects anything that is not an option, with
     `TargetLocationError`. The request schema checks it again, as it checks
     the cap of three today.
   * `search_scope` answers a scope for "Remote" and every country, and
     `None` for a region, by rule rather than by failing to parse.

3. **A country takes in its cities.**
   * Company boards often write only the city ("Taipei"). Matching a posting
     to "Taiwan" by words alone would drop every opening that says "Taipei"
     and nothing more.
   * Each country gets its main cities as extra names, in the same table
     ("Taipei", "Hsinchu", "Kaohsiung" for Taiwan). `in_market` and
     `get_open_in_scope`'s SQL read them, so a board posting in Taipei is in
     scope for "Taiwan".
   * The searches don't change: Himalayas is asked by country code.

4. **A region is matched, not searched.**
   * A posting is in a region when it is in any member country by rule 3:
     it names the country, one of its aliases or one of its cities. Remote
     work open worldwide is in every region too, as it is in every country.
   * A region adds no search. Himalayas filters by one country at a time, so
     "Europe" would be one search per member country for each candidate
     title: about 500 for one analysis, some eight minutes at one request a
     second per host, past the build's deadline and into Himalayas' rate
     limit.
   * It still sees searched postings that are young enough to count: those
     of a member country some user's build searched, and remote work open
     worldwide, searched for whoever chose "Remote".

5. **The screen.**
   * `TargetLocations.tsx` swaps the text input for a searchable select:
     type to filter, pick to add. Options are grouped Remote, Regions,
     Countries, and places already chosen are shown but can't be picked.
   * Chips, the "n of 3 chosen" count and removing a location stay as they
     are. Each change still saves the whole set and emits
     `TargetLocationsChanged`, which no longer rebuilds anything by itself
     (next section).
   * A chosen region's chip is marked, with one line under the list: "Regions
     use the postings we already have. Pick a country for a fresh search of
     your recommended roles." The copy no longer says "City, country or
     Remote region".

6. **Stored locations are moved over.**
   * A migration rewrites each `market_user.market_preference` row to its
     option: "UK" → "United Kingdom", "Remote Taiwan" → "Taiwan", "EU" or
     "Remote EU" → "Europe", dropping duplicates.
   * A row that maps to no option (a city, an unknown region) is deleted, so
     the user sees one fewer location, or none. No event is recorded: the
     role map says its locations changed, and is rebuilt when the user asks.

Tests:
* Unit: options are "Remote", the regions, then the countries, each group A
  to Z, one per country; every country is in a region;
  `chosen_target_locations` rejects an unlisted place; a country takes in a
  posting that names only one of its cities; a region takes in a posting in
  any member country and remote work open worldwide, and nothing else;
  a region requests no search; the migration's mapping, including a
  dropped city.
* Integration: `GET /target-location-options`; `PUT /target-locations`
  answers 422 for an unlisted place; a Taipei-only posting counts toward
  "Taiwan" and "Asia-Pacific" in `GET /market-scope`.
* SPA: filtering and picking an option, the groups, a chosen option can't be
  picked twice, the cap of three, the region note.

What gets harder:
* A user can no longer narrow to one city. "Taiwan" takes in all of Taiwan,
  and a user who only wants Taipei sees Kaohsiung too.
* A region's searched postings depend on what other users chose. A user who
  picks only "Europe" gets board postings and worldwide remote work, but the
  candidate roles are never searched for in Europe on their behalf, and the
  screen has to say so.
* The city names per country and the countries per region are lists someone
  keeps up. A missing city quietly drops that city's board postings.
* Users who typed a city lose that location in the migration.

Open questions:
* Whether a deleted location should be named once on the screen ("Taipei is
  now part of Taiwan — add it?") rather than just disappearing. There are
  few accounts yet, so the first cut just deletes.
* Which cities each country lists. Start from the cities that appear in the
  crawled postings, and grow the list as new ones show up.
* Whether a region should one day search a few of its largest member
  countries. That would make it fresher, but which countries stand for a
  region is a judgement the user can't see.

## Fetch the market and build the role map only on demand
Today the market moves the role map. The crawler crawls every source weekly,
and the Himalayas searches between runs. Each change becomes
`PostingsChanged`, the worker's fan-out resolves it to every user in that
place, and each of them gets a rebuild and a `compute_fits` on their own key,
asked for or not. An analysis builds twice: once at once from what was
crawled (ADR 0020), and again when its searches land (ADR 0025).

From here, a role map is built only when the user asks, with an action whose
cost they confirmed: an analysis, "Rebuild role map", or adding a custom
role. A build fetches what it needs first, reusing anything fetched recently
for anyone, and is built once. Nothing is fetched for a user who asks for
nothing.

One branch, `feature/<ticket>/market-on-demand`, cut from mainline after the
location list has merged. Its ADR (0026 at the time of writing) supersedes
domain decision 14 (weekly crawl) and amends ADRs 0018, 0020, 0024 and 0025.

1. **A source is fetched when a build needs it and it isn't fresh.**
   * Every crawl source, a company board or a search, is one shared row, as
     now. It gains `due_at`: set when a build needs it, cleared when it is
     fetched.
   * A source is fresh when it was last fetched within its window, two
     optional `.env` settings:
     * `MARKET_SEARCH_FRESH_HOURS`, 72 by default. A search is a request to
       one shared, rate-limited API, so it is reused longer.
     * `MARKET_BOARD_FRESH_HOURS`, 24 by default. A board is one cheap
       request that lists everything its company has.
   * A fresh source is reused, whoever's build fetched it, so a source is
     fetched at most once per window however many users or rebuilds ask.
   * Marking is idempotent. Two builds that need the same stale source both
     wait on one fetch. A build also stamps `last_requested_at` on every
     source it needs, fresh or not (rule 8).
   * Creating a search uses `INSERT … ON CONFLICT (kind, endpoint) DO
     NOTHING`, so two analyses that recommend the same title at once can't
     fail on the unique constraint. This also fixes a race that exists
     today.

2. **What a build needs.**
   * The searches: each of the user's candidate titles, in each searchable
     place (a country, or "Remote"). A region or no location adds none.
   * The baseline boards (domain decision 15). They have no place, so every
     build needs all of them; there are nine.
   * The boards of the companies named on the user's custom roles, once
     discovery has found one.
   * `market.request_sources(titles, places, company_ids)` resolves these,
     marks the stale ones due, and answers with their ids. Only titles,
     places and company ids reach `market`; the user id never does.

3. **The crawler fetches what is due, and nothing else, politely.**
   * Its loop looks for due sources every `CRAWL_DUE_POLL_SECONDS`, an
     optional setting, 15 by default (a user is waiting), and fetches each
     under robots.txt and the per-host rate limit.
   * The weekly run, the two-minute look for unfetched sources, and
     `retire_idle_searches` go.
   * A fetch records `last_fetched_at` and clears `due_at`, failed or not.
   * **Back off per host.** A 429 or 403 pauses that host until its
     `Retry-After`, or for an exponential backoff starting at 15 minutes.
     Its due sources wait, logged at WARN, and builds waiting on them start
     at their deadline with what is stored.
   * **A daily ceiling per host,** `CRAWL_MAX_REQUESTS_PER_HOST_PER_DAY`,
     optional, 500 by default. Past it, due sources for that host stay due
     until the next day, and builds use what is stored. No amount of demand
     breaks it.
   * **robots.txt is cached across polls** for 24 hours, per host. It is
     cached per crawl run today, which is weekly; with a poll every 15
     seconds, that would refetch it four times a minute.
   * The crawler emits no posting events. `PostingsChanged` and
     `market.owners_affected_by` go, and so does the fan-out's SELECT-only
     policy on `market_user.market_preference`. The crawler then says
     nothing that is ever resolved to a user.

4. **A build waits for its due sources.**
   * Each trigger records the build as `waiting`, with the ids of the
     sources it waits for, in the user's own activity row. If none is due,
     it starts at once.
   * The worker's dispatch loop already reads open builds for ADR 0018's
     staleness. It now also starts a waiting build when every source it
     waits for has been fetched since the build was recorded, or when
     `MARKET_WAIT_SECONDS` (optional, 300 by default) has passed. Either
     way the build uses what is stored.
   * After an analysis, the titles come from `RoleCandidatesReplaced`, which
     is recorded before `AnalysisFinished`. The build is recorded on
     `AnalysisFinished` and asks for its sources then. A failed analysis
     still only releases a build that waited for it.
   * `BuildRun` says what it waits for, so the running bar can say
     "Searching the market for your recommended roles".

5. **A fetch replaces what its source holds.**
   * A board lists every opening its company has, so one missing from a
     successful fetch is closed, and it expires, as now.
   * A search shows only its first page (robots.txt forbids paging). Each
     successful fetch replaces that search's result list, a new table
     `market.search_result (crawl_source_id, job_posting_id, rank,
     fetched_at)`. A job pushed off the page leaves the list; the posting
     row is not deleted, and stays open while a board or another search
     still holds it.
   * A build's searched postings are exactly the current lists of the
     searches it needed. Search fetches stop calling `expire_unseen`.
   * A failed or skipped fetch (backoff, the daily ceiling, the crawler
     down) leaves the old list in place. A build at its deadline uses it,
     and the map says how old it is.

6. **The search decides which role a posting belongs to, and a local
   estimate picks the ten, with no extra tokens.**
   * **A searched posting goes to the candidate that searched for it.** A
     candidate's openings start as the current result lists of its own
     searches in the user's places. That is a lookup, not a guess, and
     replaces matching every posting to every candidate.
   * **Loose hits are dropped.** Himalayas matches the query against the
     description too, so a "Data Engineer" search returns some jobs that
     aren't. A searched posting stays with its candidate only when its title
     has the candidate's title words, or its embedding is at least
     `CANDIDATE_MATCH_THRESHOLD` (0.40) similar to the candidate's. Otherwise
     it is left out, not handed to another candidate.
   * **A posting two searches returned counts once**, for the candidate it
     is more similar to.
   * **Board postings** weren't searched for anyone. They are assigned by
     embedding or title words, as today, and can add openings to any
     candidate.
   * **Every candidate with at least three openings gets a local fit
     estimate.** It costs nothing on the user's key: it uses the same local
     embedding model as the matching, and runs before anything is sent to
     the model.
     * The user's side is their current dimensions, each weighted by score
       × confidence. `assessment` hands them to `rolemap.replace_candidates`
       with the candidates (names and weights only, no evidence), and
       `rolemap` keeps them beside the candidates, in a new owner-zone table
       with row-level security, replaced with them. `rolemap` still imports
       nothing from `assessment` (ADR 0018).
     * The role's side is the centroid of its openings' embeddings.
     * The estimate is the weighted mean of each dimension's similarity to
       that centroid: roles whose openings read like the user's strongest
       dimensions come first.
   * **The ten are the ten with the best estimate**, the analysis's own
     rank breaking ties. Today it is the first ten in the analysis's order.
   * **Only those ten are analysed on the user's key**, then scored by
     `compute_fits`, exactly as today. The paid calls per build don't
     change; only which ten get them does.
   * The role map orders and plots roles by the real fit once it is scored.
     The estimate only chooses the ten, and is never shown as a fit.
   * Each build logs how well the estimate's order agreed with the fits
     `compute_fits` then scored, as a rank correlation, with no user data.
     That is the evidence for keeping the estimate or going back to the
     analysis's order.

7. **What no longer builds the map.**
   * A change of target locations. The role map says "Your locations
     changed" with Rebuild and its estimate. The next build searches the new
     places.
   * A market change. There is none to hear any more.
   * The role map shows "Market data as of …": the oldest fetch among the
     sources its last build used.
   * "Keep your map current" stops saying the map is rebuilt "when the
     market in your locations changes". Its Rebuild button reads "Searching
     the market…" while a build waits on sources, as well as "Waiting for
     analysis…".

8. **What nobody asks for stops taking room.** Users who stop coming back
   cost no bandwidth, since nothing is fetched without a build, but their
   searches and postings stay stored. `market` cleans up from its own
   facts, because it can't see who references a posting, and must not: that
   would be a cross-user read again.
   * A search no build has needed for `MARKET_SOURCE_IDLE_DAYS` (optional,
     90 by default) is deleted with its result list. A board is never
     deleted, only no longer fetched.
   * A posting is held while it is open on a board or on a current result
     list. One unheld for `POSTING_THIN_AFTER_DAYS` (optional, 180 by
     default) is thinned. Its description and embedding are dropped. Its
     id, title, company, location, link, salary and dates stay, a few
     hundred bytes.
   * Thinning, not deleting, keeps every reference whole: a Target's opening
     (`job_posting_id` in plans, résumés and gap questions), a stale role
     map's members, and salary history. A Target's requirements are frozen
     in its snapshot, so they never needed the description.
   * The sweep runs once a day in the crawler's loop, on `market` rows only.

Tests:
* Unit:
  * A source fetched within its window is not marked due, and an older or
    unfetched one is, with searches and boards on their own windows.
  * Two builds needing the same stale source mark it once.
  * Creating a search that already exists is a no-op, not an error.
  * A build with nothing due starts at once. One with due sources waits,
    starts when they are all fetched, and starts at `MARKET_WAIT_SECONDS`
    if they aren't.
  * A failed fetch counts as fetched for waiting and replaces nothing.
  * A 429 pauses the host and honours `Retry-After`; the daily ceiling
    stops fetches but not builds; robots.txt is fetched once per host per
    day.
  * A board fetch still expires a missing posting. A search fetch replaces
    its list, and a posting dropped from it stays open while a board or
    another search holds it.
  * A search idle for `MARKET_SOURCE_IDLE_DAYS` is deleted with its list;
    an unheld posting past `POSTING_THIN_AFTER_DAYS` loses its description
    and embedding and keeps the rest; a held one is untouched.
  * A candidate's search results become its openings; a loose hit is
    dropped, not reassigned; a posting two searches returned counts once;
    board postings still match by embedding or title words.
  * The local estimate ranks a role whose openings read like the user's
    strongest dimensions above one that doesn't, and the analysis's rank
    breaks a tie; only the ten chosen are analysed.
  * A location change rebuilds nothing.
  * Each setting's default, and that each rejects a value below 1.
* Integration:
  * One analysis leads to one build and one `compute_fits`, with the
    searched postings in scope.
  * A second analysis with the same titles within the window fetches
    nothing and builds at once.
  * The crawler fetches only due sources.
  * The daily sweep against real rows.
* SPA: the running bar's "searching the market" state, "Your locations
  changed" with Rebuild, and "Market data as of …".

What gets harder:
* The map is as old as the user's last request. A map built a month ago
  shows month-old openings until the user rebuilds, and the screen has to
  say so. "The role map rebuilds and rescores as the market moves" in
  `CLAUDE.md` stops being true.
* A build arrives later, after its sources are fetched: seconds when they are
  fresh, up to `MARKET_WAIT_SECONDS` when Himalayas is slow, the host is
  backed off, or the crawler is down.
* Salary-band history only grows when someone builds, so it is patchy for
  places few users target.
* Closed openings on a board stay open until a build fetches that board, so
  a stale map can show a job that is gone. A job pushed off a search's first
  page leaves the next map though it may still be open.
* A user coming back after months finds thinned openings on their old map:
  title, company and link, with no description, until they rebuild.
* A waiting build has two meanings (an analysis, or the market), so ADR
  0018's rule and the activity copy widen.
* Seven new settings, each with a default someone has to tune.
* The ten are chosen by a local estimate that the user never sees, and a
  small embedding model's sense of "reads like your strengths" is coarse.
  It can keep a role the model ranked low and drop one it ranked high, and
  the fits scored afterwards may disagree with the choice.
* `rolemap` holds a copy of the user's dimension names and weights, kept in
  step with every analysis.

Open questions:
* The windows (72 h and 24 h), `MARKET_WAIT_SECONDS` (300) and the daily
  ceiling (500) are guesses. Measure how long a build's due sources take,
  how often a re-analysis lands inside a window, and Himalayas' real
  requests per day, before settling.
* Whether the estimate chooses better than the analysis's order. Compare
  the logged rank correlation over a few weeks of builds before calling it
  settled, and fall back to the analysis's order if it is weak.
* Whether to search only the top 10 candidates instead of 20, if the
  ceiling is reached often. That halves the requests per new analysis.
* Whether a region-only user should be told on the role map that their
  recommended roles weren't searched, beyond the note in 01 Sources.
* Whether "Rebuild role map" should offer to refresh only the market, with
  no naming, when the candidates haven't changed. That would need a
  cheaper build path.
