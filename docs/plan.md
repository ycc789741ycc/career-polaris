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
   for the sources it needs that aren't fresh. Its follow-up is two more
   branches: the fit moves into the role map, then only the top k roles are
   named, analysed and scored, with k and the candidate count as settings.

Both have the same definition of done as Phase 5: tests in the right tier,
every gate passing with nothing skipped, an ADR each with the index, and
`CLAUDE.md`, `README.md` and `docs/architecture.md` saying what is built.

## Choose target locations from a list
**Done** ([ADR 0026](decisions/0026-choose-target-locations-from-a-list-of-countries-regions-and-remote.md)).
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
**Done** ([ADR 0027](decisions/0027-fetch-the-market-only-when-a-build-needs-it.md)). Where the
build differs from the plan below:

* A waiting build is checked by a deferred `rolemap.await_market` job of its
  own, as its owner. A dispatch-loop scan of every waiting build would have
  read across users.
* An idle search is retired with its list emptied, not deleted: its postings
  keep their source.
* The estimate centres each dimension's similarity over the candidates, and
  weighs the dimensions a candidate rests on fully and the rest at a quarter.

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
location list has merged. Its ADR (0027 at the time of writing) supersedes
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
* Whether a region-only user should be told on the role map that their
  recommended roles weren't searched, beyond the note in 01 Sources.
* Whether "Rebuild role map" should offer to refresh only the market, with
  no naming, when the candidates haven't changed. That would need a
  cheaper build path.

### Follow-up: score only the top k, inside the role map
Two things are still fixed in code that should not be. What a build spends
on the user's key follows `RECOMMENDED_ROLE_COUNT`, a constant of ten, and
the analysis recommends a constant twenty candidates that are all searched.
Both should be numbers the operator sets. And the fit, which compares the
user with a role, lives in `assessment`, which otherwise only describes the
user. A fit is about the role, and belongs beside it.

So:

* The analysis recommends `ROLE_CANDIDATE_COUNT` candidate roles, 10 by
  default, and every one is searched for.
* A build keeps the top `ROLE_MAP_TOP_K` of them by the local estimate, 10
  by default. Only those k are named, analysed and scored: three calls each
  on the user's key, and nothing for the rest. The role map shows those k.
* Custom roles stay outside the k. Every one is placed and scored, as now,
  because the user asked for it by name.
* The fit, its gaps (the user's score against the role's target), its
  uncovered requirements, the lifts that would close them, and the ranking
  of matched openings all move into `rolemap`. `assessment` keeps only the
  strength report.

Two branches, in this order, because a branch that needs two kinds is two
branches. Both are cut from the Phase 6 epic and merged back into it.

#### `refactor/<ticket>/fits-in-rolemap`: the fit moves into the role map
**Done** ([ADR 0028](decisions/0028-score-the-fit-in-the-role-map.md)). Where the
build differs from the plan below:

* The fit's body drops `private_posting_id` and its `role_id` is never null;
  paths stay the same. The SPA read neither.
* `assessment.estimate_cost` asks `rolemap` for the build's estimate and its
  fits' separately, as the role map's own estimate route does, rather than in
  one call.
* At most `MAX_STRENGTHS` (10) dimensions are handed over, the number a fit is
  priced for, and each must be scored 0 to 100 with a confidence from 0 to 1.
* The migration also gives strengths to a user whose latest analysis predates
  the hand-over, so their fits can be scored without analysing again. Fits
  for pasted JDs, unwritten since ADR 0022, are not carried over.
* The ledger names a fit projection `rolemap.fit`; older rows keep
  `assessment.fit`.

Behaviour does not change; only where the fit lives.

1. **What moves.**
   * The `RoleFit` entity, its repository and its table:
     `assessment.role_fit` becomes `rolemap.role_fit`. A migration moves
     the rows and keeps owner-zone row-level security. The obsolete
     `private_posting_id` path (scoring a pasted JD on its own, gone since
     ADR 0022) is dropped.
   * `evaluate`, `FitResult`, the gaps, `closing_lifts` and `ClosingLifts`
     from `assessment/domain/fit.py`, and `rank_matches` from
     `assessment/domain/matches.py`.
   * The `fit_projection` call, `RoleFitsComputed`, and the Spearman log of
     the estimate's agreement with the fits, which no longer needs anything
     handed over to read the estimates.
2. **The user's side is handed down, not read up.** `assessment` stays
   above `rolemap` (ADR 0018), so `rolemap` still imports nothing from it.
   * `StrengthInput`, and `rolemap.candidate_strength` where it is stored,
     gain each dimension's `score` and `confidence` beside today's name,
     read and weight, and the `assessment_id` they came from.
   * The fit prompt's dimensions block is built from them, and a fit
     records the `assessment_id` it was scored against as a plain id.
3. **Scoring is a `rolemap` job.** `rolemap.compute_fits(owner_id)` runs on
   the `ai` queue, and the dispatcher routes `RoleMapBuildFinished` to it
   instead of to `assessment.compute_fits`. It stays a job of its own, not a
   step of the build, so a failure while scoring does not fail or repeat
   role analysis the user has already paid for.
4. **Callers ask `rolemap`.**
   * `target` reads a role's fit, and `gapplan` ranks gaps by it, from
     `rolemap` instead of `assessment`.
   * `estimate_fits` moves too, and `assessment.estimate_cost` asks
     `rolemap` for the build and its fits in one estimate.
   * `/fits`, `/fits/compute` and `/matched-postings` move to
     `api/routes/rolemap.py`, with their schemas to `api/schemas/rolemap.py`.
     Paths and bodies stay the same, so the SPA does not change.
5. **What `assessment` keeps:** analysis runs, dimensions and their scores,
   lineage, the candidates it hands over, and the strength report. Nothing
   about roles.
6. **Its ADR (0028 at the time of writing)** records the move. It amends
   ADR 0018, where the fit belongs to the User × Role pair in `assessment`,
   and ADR 0024, and moves Fit from the Assessment context to the Role Map
   context in `docs/domain_model.md`. The import-linter contracts do not
   change.

Tests:
* Unit: the fit tests in `tests/unit/advisor/assessment/test_domain.py`
  and `test_matches_domain.py` move to `tests/unit/advisor/rolemap/` with
  the code; `compute_fits` builds its prompt from the handed-down scores.
* Integration: `rolemap.role_fit` keeps row-level security; the migration
  carries existing fits over; `/fits` and `/matched-postings` answer as
  before.

#### Found while building it: merged-away roles stayed on the map
`bugfix/<ticket>/stale-merged-roles`, **done**. Reconciliation recorded a merge
but never retired the roles it absorbed, so they stayed live with their old
postings: extra bubbles, ranked in Top matched under old fits, and scored by
every build's fits. A dev account had 23 live recommended roles against a k of
10. Absorbed roles are now retired (once), migration 0024 retired the ones
already left behind, and the map counts each role's openings live, so a bubble
and "Top matched openings" always name the same roles and openings.

#### `feature/<ticket>/role-map-top-k`: the two counts become settings
**Done** ([ADR 0029](decisions/0029-set-the-candidate-count-and-the-top-k-as-settings.md)). Where the
build differs from the plan below:

* `ROLE_CANDIDATE_COUNT` is also capped at 20, the old constant: each
  candidate is one Himalayas search per searchable place.
* The reply's schema is built per service with the configured maximum, so a
  reply with too many candidates fails validation and the gateway asks
  again, rather than being cut short.
* `keep_on_market` takes no limit by default; a build keeps every candidate
  with openings eligible and lets `choose_by_estimate` cut to k.
* The SPA already said `max_roles` wherever it showed the number; only
  comments said "ten".

1. **Two optional `.env` settings**, read once into `Settings` and validated
   at startup:
   * `ROLE_CANDIDATE_COUNT`, 10 by default: how many roles an analysis
     recommends, all of which are searched for. It replaces
     `CANDIDATE_ROLE_COUNT` (20).
   * `ROLE_MAP_TOP_K`, 10 by default: how many recommended roles a build
     keeps, names, analyses and scores. It replaces `RECOMMENDED_ROLE_COUNT`.
   * Each is at least 1, and `ROLE_MAP_TOP_K` is at most
     `ROLE_CANDIDATE_COUNT`, or startup fails.
   * They reach the services through each component's `factory.py`, as
     `confidence_threshold` and the market's windows do. The domain rules
     take them as parameters (`choose_by_estimate(limit=…)`,
     `keep_on_market(limit=…)`, `max_role_count(…, ceiling=…)`), so no
     constant is left behind.
2. **The analysis asks for the configured number.**
   * The output schema's candidate list takes its maximum from the setting,
     and `replace_candidates` checks it again.
   * A new `skill_assessment` v3 template says "Recommend up to
     {candidate_count} roles". v2 says twenty, and templates are versioned,
     not edited.
3. **A build names, analyses and scores only the top k.**
   * `choose_by_estimate` keeps k of the candidates with at least three
     openings. Nothing else is sent to the model.
   * Custom roles are placed and scored on top of the k.
   * `compute_fits` scores every live role with requirements, which is the
     k plus the custom roles.
   * Candidates outside the k are recorded unplaced, with their opening
     count and estimate, so `GET /role-candidates` still names them.
4. **Estimates price k.** `rolemap.estimate_cost` and `estimate_fits` use k
   where they use ten now: the full k when the user has a searchable place,
   otherwise `max_role_count` capped at k.
5. **The screen** says the number it is given (`max_roles`), never "ten".
6. **Its ADR (0029 at the time of writing)** supersedes ADR 0020's count
   "fixed by the system, with no setting" and domain decision 23, and amends
   ADR 0024's twenty candidates.

Tests:
* Unit: both defaults; startup rejects 0, and a k above the candidate
  count; an analysis reply with more candidates than configured is
  rejected; only the top k are analysed, and fits are scored for the k
  plus the custom roles; estimates scale with k; candidates outside the k
  are listed unplaced.
* Integration: at a small k (3), one analysis leads to one build that
  names three roles, and three fits.

What gets harder:
* Two more settings to tune, and what a build costs differs between
  deployments. The ten is no longer something a reader finds in the code.
* With ten candidates instead of twenty, there are fewer spares. A market
  that lacks several of them shows fewer than k roles.
* `rolemap` holds a copy of the user's dimension scores and confidence, not
  only their weights, kept in step with every analysis.
* Moving `role_fit` is a migration over every user's fits.

Open questions:
* Whether k should one day be the user's choice rather than the
  deployment's. The cost confirm already shows what it buys.
* Whether ten candidates leave narrow markets thin. Watch
  `candidates_on_market` in the `rolemap.selected` log before lowering the
  default further, or raising it back.

# Phase 7
Housekeeping that changes no behaviour: no endpoint, table, migration or
screen changes. One branch for now; more items can join this phase later.

## Split each domain by concept
**Done**. Where the build differs from the plan below:

* The market's word rules (`normalize`, `normalize_title`,
  `names_every_word`, `market_words`, `clip`, `ACCENT_FOLDS`) move out of
  `posting.py` into a concept of their own, `words.py`. Moving `Company` to
  `source.py` and `SourceKind` out of `posting.py` turned the old one-way
  imports into a cycle: `source.py` needed `normalize` from `posting.py`,
  and `posting.py` needed `SourceKind` from `source.py`. The rules were never
  about postings. Companies, places and searches compare words through them
  too, so with them in `words.py` every import points one way.
* Each `constants.py` groups its values under a header naming the module
  whose rules use them, which keeps finding a limit's rule one step away.
  `profile` and `target` have no literal constants, so no `constants.py`.
* The guard also refuses `value_objects.py` and `helpers.py`, as the
  design guideline does.

Today a component's `domain/` is split two ways at once. `entities.py` holds
every class a repository loads and saves, whatever concept it belongs to. The
other files are each named after one concept and hold its rules: `fit.py`,
`selection.py`, `password.py`. So a concept's state and its rules live apart:
`RoleFit` sits in `entities.py`, while what makes a fit sits in `fit.py`. The
largest `entities.py` files (`rolemap`, `market`, `identity`) mix four to
seven unrelated aggregates in 230 to 380 lines. A file name says what kind of
code it holds, not which concept, so finding `BuildRun` means knowing the
convention first. `profile/domain/evidence.py` already breaks the convention,
keeping `Evidence` beside the citation rules, and it is the clearest file in
its domain.

Its own branch, `refactor/<ticket>/domain-by-concept`, cut from mainline once
the Phase 6 epic has landed. Every Phase 6 branch touches these files, so
starting earlier means resolving the same moves twice. One commit per
component, so each one reviews and reverts on its own.

1. **A concept file holds the concept's entities, value objects, enums,
   errors and rules together.** It is named for the concept in the domain's
   own words (`role.py`, `build_run.py`), never for a kind of code (`models.py`,
   `entities.py`, `rules.py`, `types.py`). `entities.py` goes away in every
   component.
2. **Exactly three files stay split by kind.**
   * `repositories.py`: the repository and unit-of-work Protocols (ADR 0011).
   * `events.py`: the domain events.
   * `constants.py`: the domain's public named values.
3. **What counts as a constant.** Every public module-level
   `SCREAMING_SNAKE_CASE` value with a literal value moves to `constants.py`.
   That covers limits, thresholds, counts, durations and fixed codes, such as
   `MAX_ROLE_TITLE`, `SAME_ROLE_THRESHOLD`, `LOCKOUT_WINDOW` and `STALE`.
   * `constants.py` is a leaf. It imports only the standard library and
     nothing from its own component, so any concept file can import it
     without a cycle.
   * That rules out three kinds of value, which stay beside the code that
     owns them:
     * private `_`-prefixed values, such as compiled patterns and lookup
       indexes;
     * catalogues built from a concept's own types (`COUNTRIES`, `REGIONS`,
       `SUGGESTED_MODELS`);
     * values computed by a domain function (`WORLDWIDE_WORDS`).
   * A component with no such value has no `constants.py`.
4. **`domain/__init__.py` keeps exporting the same names**, so nothing
   outside `domain/` changes: not `service.py`, `jobs.py`, `infra/`, routes
   or tests. Inside `domain/`, `repositories.py` and the concept files import
   from the new modules.
5. **Where each entity goes:**

   | Component | Moves |
   |---|---|
   | `rolemap` | `Role`, `RoleOrigin`, `CustomRoleError`, `RoleMember`, `RoleRequirement` → `role.py`; `RoleCandidate`, `CandidateStrength` → `candidate.py`; `BuildRun`, `BuildRunStatus` → `build_run.py`; `RoleFit` → `fit.py`; `LineageEntry` → `identity.py`, renamed `lineage.py` (it reconciles roles and records their lineage, and `identity` is also a component's name) |
   | `market` | `Company`, `CrawlSource`, `SourceStatus`, `FreshWindows`, plus `SourceKind`, `SourceOrigin` from `posting.py` → `source.py`; `JobPosting`, `PostingEmbedding`, `PostingScope` → `posting.py`; `SearchResult` → `search.py`; `PrivateJobPosting` → `private_posting.py`; `MarketPreference`, `TargetLocationError`, `chosen_target_locations` → `target_locations.py` |
   | `identity` | `Account` → `account.py`; `PasswordCredential` → `password.py`; `FederatedIdentity` → `federated.py`; `RefreshToken` → `tokens.py`; `ProviderCredential` → `credential.py`; `AiUsageBudget`, `AiUsageEntry` → `budget.py` |
   | `profile` | `SourceConnection`, `ConnectionStatus` → `connection.py`; `ResumeFile`, `ResumeStatus` → `resume_file.py`; `CareerPosition` → `timeline.py`; `ProfileVersion` → `profile_version.py` |
   | `assessment` | `SkillDimension`, `DimensionChange` → `dimensions.py`; `SkillAssessment`, `AssessedScore` → `skill_assessment.py`; `AnalysisRun`, `AnalysisRunStatus` → `analysis_run.py` |
   | `gapfill` | `QuestionSet`, `QuestionSetStatus`, `GapQuestion` → `questions.py` |
   | `gapplan` | `GapPlan`, `Milestone`, `Task` → `plan.py` |
   | `resume` | `TailoredResume`, `ResumeStatus`, `ResumeVersion` → `tailored_resume.py`; `Revision` → `revision.py`; `Export`, `ExportStatus` → `export.py` |
   | `target`, `activity` | Nothing to split. `activity` gains a `constants.py` for `STALE`. |

   Only entities and constants move. A rule moves too only where this table
   names it. Anything else that might read better elsewhere, such as
   `settle_revision` beside `Revision`, is a separate change.
6. **A guard keeps it that way.** A unit test walks every
   `advisor/*/domain/` package. It fails on any module named `entities.py`,
   `models.py`, `rules.py` or `types.py`, and on any `constants.py` that
   imports something other than the standard library.
7. **The docs say the new shape.** `CLAUDE.md`'s "Shape of the code" and
   `docs/architecture.md`'s module tree list `repositories.py`, `events.py`,
   `constants.py` and one file per concept. ADR 0010, which drew
   `entities.py`, is already superseded and stays as written.

No ADR. The rule is now the design guideline's ("Modules in the domain: one
per concept" in `base/backend/architecture.md`), which also moves every
repository interface into `repositories.py`, as this repo already does. This
branch brings the code in line with it.

Tests:
* No behaviour changes, so no test changes beyond the guard. `make
  test-unit`, `make test-integration`, `lint`, `typecheck` and the
  import-linter contracts pass unchanged. A test that needed editing would
  mean a name stopped being exported from `domain/__init__.py`.
* Unit: the layout guard, which is shown to fail on a stray `entities.py`
  before it lands.

What gets harder:
* No single file lists everything a component stores. `domain/__init__.py`
  and `repositories.py` are the listing now.
* Concept files import each other more (`role.py` reads `hiring_bar` and
  `lineage`), so an import cycle is easier to write. `constants.py` being a
  leaf, and `from __future__ import annotations`, keep that rare.
* A limit sits in `constants.py`, away from the rule that enforces it, so
  reading a rule means opening two files.
* `git blame` on the moved lines points at the move. Use
  `git log --follow` or blame with `-C`.

Open questions:
* Whether a concept that outgrows one file becomes a subpackage
  (`domain/role/`). Not needed by anything today, the largest being
  `market/domain/places.py` at 333 lines.

# Phase 8
The role map becomes the market's side only, and evaluating the user moves
out of it.
* A **Role** is a group of openings and what they ask for: no company of its
  own, no JD, nothing about the user.
* A **RoleFit** is the evaluation: the user's strengths against a role, and
  it references the role.
* A **role candidate** is the query a build searches and matches with.
* A **PostingFit** is the evaluation of one posting: an opening in a role,
  or one the user brought themselves. It is never an AI call. The AI
  evaluates a set of requirements once, a role's (`RoleFit`) or a pasted
  JD's (`PostingRequirementFit`), and every `PostingFit` is worked out from
  that locally.

A posting the user brings themselves is aimed at from the Advisor, not added
to the map. Four branches, in this order, each cut from an epic,
`epic/<ticket>/phase-8`, cut from mainline:

1. "A posting of your own is a Target, not a role": custom roles leave the
   role map, and `Role` loses everything only they used.
2. "A role candidate is only a query": what a build made of each candidate
   becomes a record of that build.
3. "Score a fit only when what it reads has changed": a rebuild on an
   unchanged market and unchanged strengths spends nothing.
4. "A fit for every opening": each opening in a role gets its own fit,
   worked out locally from its role's, and Top matched openings lists the
   selected role's openings by it.

The definition of done is Phase 5's: tests in the right tier, every gate
passing with nothing skipped, an ADR each with the index, and `CLAUDE.md`,
`README.md` and `docs/architecture.md` saying what is built.

## A posting of your own is a Target, not a role
Today "Add a role of your own" (03 Roles) creates a `custom` `Role` from a
title, an optional company and an optional pasted JD (ADR 0021).
* It joins the role map, and every build matches it to postings by title
  words, asks for its company's board, and analyses and fit-scores it.
* What the user wants from it is to aim the Advisor at one posting. The role
  map only ever offers them a role and one of its openings, so a posting
  they found themselves has nowhere else to go.
* It puts a company and a JD on `Role`, which is otherwise a group of
  openings, and makes every build spend on a role the market did not make.

In dev data: two live custom roles, both with a company and a JD, and one
plan, one résumé and one question set aimed at them.

Its own branch, `refactor/<ticket>/own-posting-target`.

1. **The Advisor takes a posting of the user's own.** "Aim at a posting of
   your own" in 04 Advisor (title, company, pasted JD) replaces "Add a role
   of your own" in 03 Roles.
   * The JD is stored as today, in `market_user.private_job_posting`, which
     the crawler cannot reach.
   * Before anything runs, its cost is confirmed: reading the JD's
     requirements, then scoring the fit, on the user's key.
   * The Advisor's hash names it as `?posting=<private_job_posting_id>`,
     instead of `?role=` and `&opening=`.
   * A JD is required: without one there is nothing to read requirements
     from, now that nothing searches the market for it.
2. **A Target is a role (and optionally one of its openings), or a posting
   of the user's own.** `TargetRef` takes either `role_id` with an optional
   `job_posting_id`, or `private_job_posting_id` alone, and refuses both or
   neither. `gapplan.plan`, `resume.resume` and `gapfill.question_set` gain
   a nullable `private_job_posting_id`, `role_id` becomes nullable, and a
   check constraint keeps exactly one of them set. A posting of your own's
   requirement basis is its JD, as a custom role's was. In `TargetSnapshot`,
   `role_id` and `role_name` become optional, and its label comes from the
   title and company the user entered.
3. **The posting is evaluated beside the role fits, not in the map.** In
   `rolemap`, which keeps the one set of fit rules (ADR 0028):
   * `PostingRequirement` (table `rolemap.posting_requirement`) describes
     the posting: what its JD asks for, read once when it is added.
   * `PostingRequirementFit` (table `rolemap.posting_requirement_fit`) is
     the AI's evaluation of those requirements against the user's
     dimensions. It is the `fit_projection` call a `RoleFit` makes, giving
     the mapping, the targets and the reasoning, but over the JD's
     requirements instead of a role's.
   * `PostingFit` (table `rolemap.posting_fit`, `basis = own`) is worked out
     from it locally, with no AI. `evaluate` runs over the JD's requirements
     at their own weights, since nothing needs reweighting when the
     requirements come from this one posting. It carries the score, gaps,
     uncovered requirements and closing lifts the Advisor reads. It
     references the posting by `posting_key` (`private:<id>`), as
     `rolemap.role_member` does, so the fourth branch stores openings' fits
     in the same table.
   * Adding a posting of your own costs two calls, `rolemap.extract` then
     `rolemap.fit`. Nothing else on it calls the AI.
   * None of them is listed, counted or drawn by the role map, and no build
     reads or scores them.
   * After a new analysis, the Advisor says the posting's fit was scored
     against earlier strengths and offers to rescore it, with its cost. A
     rescore re-runs the `PostingRequirementFit` call, and the `PostingFit`
     is worked out again from it. Nothing is rescored unasked.
4. **The role map loses custom roles.**
   * Gone: `RoleOrigin`, `CustomRoleError`, `add_custom_role`, `POST
     /roles/custom`, `/roles/custom/cost-estimate`, `CustomRoleAdded`, and
     the "Your roles" part of 03 Roles.
   * A build no longer asks for custom roles' companies' boards. Board
     discovery (`market.discover_board`) has no caller left and goes with
     them.
   * `Role` loses `origin`, `company_name` and `private_posting_id`. Its
     docstring says what it is: a group of openings in the user's target
     locations, with what they ask for. Every role is recommended, and k
     roles is the whole map.
5. **A migration moves what is there.** For each custom role with a JD:
   * its requirements become the posting's requirements;
   * its latest fit becomes the posting's fit;
   * the plans, résumés and question sets aimed at it are pointed at the
     private posting.

   Then the role is retired. A custom role without a JD is retired, and what
   was aimed at it stays as history, like any retired role's. It lifts
   `FORCE ROW LEVEL SECURITY` while it writes and guards with `IF EXISTS`.
6. **An ADR** supersedes ADR 0021 and the parts of ADR 0022 (a Target is
   always a role) and ADR 0027 (a build asks for custom roles' boards) it
   changes, with the index updated.

Tests:
* Unit:
  * `TargetRef` refuses both or neither;
  * a snapshot for a posting of your own reads its JD's requirements and
    its `PostingFit`, with no role;
  * its `PostingFit` is worked out from its `PostingRequirementFit` with a
    gateway that fails on any call;
  * a build has no custom roles to match, analyse or score;
  * the role map lists no posting of your own;
  * rescoring after a new analysis is offered, not run.
* Integration:
  * adding a posting of your own stores the JD, its requirements and its
    fit under row-level security, and another owner reads none of them;
  * a plan and a résumé aimed at it draft against its JD;
  * the migration moves a custom role with a JD and its plan, retires one
    without, and runs twice without harm.

What gets harder:
* A Target has two shapes, so every reader of `TargetRef` handles both, and
  the three tables carry two nullable columns and a check.
* A posting of your own is no longer matched to other postings like it, so
  nothing tells the user how many similar openings the market has.
* `rolemap` scores something that is not on the map. The fit rules stay in
  one place, at the cost of the component's name meaning a little less.
* A posting's fit can go stale after an analysis until the user rescores it.

Open questions:
* Whether a posting of your own should be offered a role from the map that
  is like it, as a second Target to compare against.
* Whether a pasted link, rather than pasted text, should be accepted, and
  fetched once.

## A role candidate is only a query
Today `RoleCandidate` (`rolemap/domain/candidate.py`) does two jobs:

| Job | Fields | Written by |
|---|---|---|
| **The query.** The title is searched on Himalayas in each searchable place (only the title leaves the platform). Title and description are embedded to match the postings in scope (`assign_postings`). The dimension keys say which strengths the local fit estimate reads. | `rank`, `title`, `description`, `dimension_keys`, `assessment_id` | the analysis, through `replace_candidates` |
| **The last build's outcome.** The role the candidate became, how many openings it had, and the estimate that chose the k. | `role_id`, `opening_count`, `fit_estimate` | the build, through `_place_candidates` (`placed` / `unplaced`) |

The second job does not belong to the candidate.
* **The outcome is a build's, not the analysis's.** Every build overwrites
  it, so nothing says what an earlier build made of the same candidate, and
  `compute_fits`'s estimate-agreement log only ever sees the latest one.
* **It is a second copy.** A placed role's openings are counted live
  (`map_roles`, Phase 6), so the candidate's `opening_count` can disagree
  with the bubble.
* **An empty `role_id` hides why.** "The market has no openings for it"
  and "it has openings but fell outside the top k" look the same.

Its own branch, `refactor/<ticket>/candidate-as-query`, after the first.

1. **`RoleCandidate` keeps the query only:** `id`, `owner_id`,
   `assessment_id`, `rank`, `title`, `description`, `dimension_keys`,
   `created_at`. `role_id`, `opening_count`, `fit_estimate`, `is_placed`,
   `placed` and `unplaced` go.
2. **A build records a `CandidatePlacement` per candidate it read**, in
   `rolemap/domain/build_run.py` beside `BuildRun`, which owns it. Table
   `rolemap.candidate_placement`:
   * `build_run_id` → `rolemap.build_run`, `ON DELETE CASCADE`.
   * `candidate_id` → `rolemap.role_candidate`, `ON DELETE SET NULL`, with
     the candidate's `rank` and `title` copied in, so the record still reads
     after the next analysis replaces the candidates.
   * `outcome`: `placed`, `outside_top_k` (it had openings, and the estimate
     kept others) or `no_openings`.
   * `role_id` (set only when `placed`) → `rolemap.role`, `ON DELETE SET
     NULL`; `opening_count`; `fit_estimate`.
   * Unique on `(build_run_id, candidate_id)`, owner-zone with row-level
     security like every `rolemap` table.

   Its repository has the usual six methods, filtered by build run.
   `_place_candidates` creates the rows instead of updating candidates; a
   candidate an analysis replaced during the build is still skipped.
3. **The readers move to the placements of the latest finished build.**
   * `RoleMapService.candidates` (`GET /role-candidates`) joins each current
     candidate to its placement in the latest `ready` build that read it.
     `RoleCandidateView` keeps its fields, so the response, `make
     gen-client` and the SPA's "the market lacks these" list
     (`Roles.tsx`) are unchanged. A candidate no build has read yet shows no
     role and no openings, as today.
   * `_log_estimate_agreement` pairs each placed placement's
     `fit_estimate` with the fit of its `role_id`, for the build the fits
     were scored after.
4. **A migration moves what is there.** It creates the table, writes one
   placement per current candidate against the owner's latest `ready` build
   (`outcome` from `role_id` and `opening_count`: placed; else
   `no_openings` when the count is 0, otherwise `outside_top_k`), then
   drops the three columns. It lifts `FORCE ROW LEVEL SECURITY` while it
   writes and restores it, guards with `IF EXISTS`, and skips an owner with
   no finished build: their candidates read as not built yet.
5. **An ADR** supersedes the parts of ADR 0024 and ADR 0027 that put the
   outcome on the candidate, with the index updated. `docs/domain_model.md`,
   `docs/architecture.md`, `docs/technical/role-map-build.md` and
   `CLAUDE.md` say the candidate is a query and the placement a build's
   record.

Tests:
* Unit (`rolemap`): a build writes `placed`, `outside_top_k` and
  `no_openings` placements for the right candidates; the candidate itself
  is not updated; a candidate replaced mid-build gets no placement;
  `candidates` reads the latest `ready` build's placements and ignores a
  failed or older one; the agreement log reads placements.
* Integration: a build against the database writes placements under
  row-level security and another owner reads none; `GET /role-candidates`
  answers with the same body as before; the migration moves a placed, an
  unplaced-with-openings and an unplaced-without-openings candidate, and
  runs twice without harm.

What gets harder:
* "What role did this candidate become" is a join through the latest
  finished build instead of a column.
* One more table and repository in `rolemap`, and a row per candidate per
  build (at most `ROLE_CANDIDATE_COUNT` each).
* The migration has to guess the outcome of candidates placed before it,
  from counts that may already be stale.

Open questions:
* Whether the SPA should say why a recommended role is missing ("no
  openings in your locations" or "others fit better"), now that the
  outcome is recorded. That would change the response, so it is a separate
  change.
* How long placements are kept. They go with their build run, which is
  never pruned today.

## Score a fit only when what it reads has changed
A build already reuses a role whose openings are exactly the last build's:
it refreshes the count and salary bands and spends nothing on naming or
requirements (`_keep_role`). That check is keyed on the members, not on
when the searches were last fetched, on purpose:
* Searches are shared, so another user's build can refetch one.
* Boards expire postings.
* A change of locations changes the scope.

A search that is still fresh can therefore still bring different members.
But `compute_fits` re-scores every role after every build, so a rebuild on
an unchanged market and unchanged strengths still spends the key on k fits
that come out the same.

Its own branch, `feature/<ticket>/reuse-unchanged-fits`, after the second.

1. **An AI fit records what it read.** `RoleFit` and
   `PostingRequirementFit` gain
   `requirements_digest`, a hash of the requirements scored against
   (statement, weight and expected level, in order) and of the fit
   prompt's template version, and the `assessment_id` of the strengths.
   A new fit prompt therefore re-scores everything once. A `PostingFit`
   needs none of this: it costs nothing, so it is simply worked out again
   from whichever fit it came from.
2. **`compute_fits` skips a role whose latest fit read the same
   requirements and the same analysis.** It scores only the rest, and logs
   how many it reused. A posting of your own's fit is reused by the same
   rule when the user asks to rescore it.
3. **Estimates stay ceilings.** Before a build, nobody knows which roles'
   members will change, so `fits_cost_usd` still prices every role that
   could be scored. The ledger shows what was actually spent.
4. **No ADR.** It changes what is spent, not what is stored or shown, and
   reverts by removing the check.

Tests:
* Unit:
  * a second `compute_fits` with unchanged requirements and strengths
    scores nothing;
  * a changed requirement re-scores that role only;
  * a new analysis re-scores every role;
  * the digest does not depend on how the requirements are loaded.
* Integration: two builds over an unchanged market write one set of fits,
  not two.

What gets harder:
* A fit can be older than the build that shows it. Its `created_at` says
  when it was scored, not when the map was built.
* A change to the fit rules outside the prompt (the weights, the lift
  formula) does not re-score anything by itself. It needs a one-off rescore,
  or a bump of the template version.

## A fit for every opening
Today an opening has no fit of its own. Every row of "Top matched openings"
carries its role's `RoleFit` score (`fit_basis: "role"`), so all of a
role's openings score the same. The list is drawn across every role
(`/matched-postings?page_size=10`, `Roles.tsx`): ranked by role fit, one per
company. Picking a bubble does not change it.

Two openings in one role can ask for quite different things, though: one
stresses what the user is strong in, another their gap. The user should see
that difference, and see it for the role they are looking at.

Scoring each opening the way a role is scored would cost one AI call per
opening instead of one per role. Similarity alone, like `fit_estimates`,
is free but cannot give a fit. It says a topic is present, not the level
expected, so there are no targets and no gaps. Something the user lacks has
nothing to be similar to, so there are no uncovered requirements. Without
those there are no closing lifts, and the gap plan ranks by lifts. It also
rewards company blurbs and benefits that happen to sound like the user.

So the AI reads once per role, as now, and each opening's fit is worked out
locally from it.

Its own branch, `feature/<ticket>/fit-per-opening`, after the third.

1. **The AI reads once per role, unchanged.** It reads a role's
   requirements from a sample of its openings, then maps them onto the
   user's dimensions, with a target for each. That is the `RoleFit`, k calls
   per build, reused under the third branch's rule.
2. **Each opening's fit is worked out locally, at no cost.** In the worker,
   after `compute_fits`:
   * Each of the role's requirement statements is embedded once, with the
     embedding model postings already use.
   * Each statement is compared with each opening's stored embedding
     (`market.posting_embedding`). The similarity is centred on that
     requirement's mean over the role's openings, as `fit_estimates` centres
     dimensions. A requirement every opening asks for therefore weighs the
     same everywhere, and one an opening stresses weighs more there.
   * The requirement weights are scaled by that relevance. A requirement an
     opening barely mentions falls below a floor and drops out for it. The
     scale and the floor are named values in `rolemap/domain/constants.py`.
   * `evaluate` (`rolemap/domain/fit.py`) runs again with the opening's
     weights and the role fit's mapping and targets. The result is the
     opening's own score, gaps, uncovered requirements and closing lifts.
   * A new rule in `rolemap/domain/fit.py`, `fit_for_opening`, does the
     reweighting. It is pure and has no I/O.
3. **It is stored as a `PostingFit` with `basis = role`**, beside the
   `basis = own` fits of postings the user brought (first branch). It is
   keyed on the opening's `posting_key` and references the `RoleFit` it was
   worked out from. Every build re-derives its openings' fits, since this is
   free, including for roles whose `RoleFit` was reused. A stored
   `PostingFit` is a cache of a pure computation: never edited, worked out
   again at every build, and the table could be emptied and rebuilt from
   the AI fits and the embeddings without an AI call. It is stored because
   Top matched openings is a list: it sorts and pages by score in SQL, and
   its inputs change only when a build runs. An opening that left the
   market since the build drops out when the list is read, against the live
   scope.
4. **A `PostingFit` is never an AI call.** That holds for both bases. The
   code that works them out takes no AI gateway, and a unit test runs it
   with a gateway that fails on any call. The AI evaluates a set of
   requirements once, and per-posting work stays local, so the cost of a
   build grows with its roles, not with its openings.
5. **Top matched openings follows the selected role.**
   * `GET /matched-postings?role_id=` ranks the role's openings by their
     own fit. Each row carries the opening's score and `fit_basis:
     "posting"`, so `make gen-client` changes.
   * `one_per_company=true` keeps the best opening from each company. Top
     matched openings asks for it. The bubble's count and the Advisor's
     opening picker don't, and still see every opening.
   * The list across every role goes. The SPA loads the selected role's
     list, the best fit's until the user picks a bubble, and reloads it on
     every pick.
6. **Aiming the Advisor at an opening plans against the opening's fit.** A
   Target of a role and an opening takes that opening's `PostingFit`: its
   reweighted requirements, gaps and lifts. Its snapshot's
   `RequirementBasis` is a new `opening`, so the Advisor says "measured
   against this opening" rather than "against the role". A Target of a role
   alone keeps the `RoleFit`. Resolving either still spends nothing.
7. **An ADR** records the per-opening fit: what it is derived from, what it
   cannot see, and why it is not an AI call per opening. It supersedes the
   part of ADR 0022 that says an opening's fit is its role's. The index is
   updated.

Tests:
* Unit, `fit_for_opening`:
  * an opening that stresses a requirement the user is strong in scores
    above one that stresses their gap;
  * a requirement every opening asks for moves no opening's score;
  * a requirement under the floor drops out of that opening's gaps and
    uncovered list;
  * with every opening alike, each scores its role's fit.
* Unit, service:
  * openings' fits are derived after a build, including when the role fit
    was reused;
  * deriving every opening's fit makes no AI call: the gateway fails on
    any call;
  * `matched_postings(role_id=)` ranks by the opening's fit, and with
    `one_per_company` keeps one per company;
  * a Target with an opening reads the opening's fit.
* Integration:
  * a build stores one `PostingFit` per opening under row-level security;
  * `GET /matched-postings?role_id=` answers with each opening's own score.
* SPA: picking a bubble reloads Top matched openings for that role.

What gets harder:
* An opening's fit can only see what its role's requirements name. A
  requirement only that opening asks for is invisible to it. The exact fit
  for one opening would need an AI call over its description.
* One embedding per opening blurs a long description, so the reweighting is
  coarse. It ranks openings within a role; it is not a verdict on one.
* A row per opening per build in `rolemap.posting_fit`.
* The worker embeds every requirement statement on each build. That is
  local CPU time, on the queue a build already uses.
* The Advisor's plan for an opening can differ from its plan for the role,
  and both show.

Open questions:
* Whether aiming the Advisor at an opening should offer an exact fit, one
  AI call over that opening's description, priced and confirmed like a
  posting of your own.
* Whether openings should be embedded in chunks rather than whole, so a
  requirement mentioned once in a long description still counts.
