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
**Done** (ADR 0030, migration 0025). Where the build differs from the plan
below:

* Reading and scoring a posting is a job, recorded before it is queued as a
  `PostingEvaluation` run (`rolemap.posting_evaluation`) that the Advisor
  polls, as every AI job is (ADR 0006).
* The posting's fit is kept as two records, as the plan's later revision
  says: the AI's `PostingRequirementFit`, and the `PostingFit` worked out
  from it locally (`get_posting_fit`), so a `PostingFit` is never an AI call.
* The probing half of board discovery went with its job; recognising a board
  URL stays, in `market/crawling/board_urls.py`.
* Routes take the three Target ids through `api.dependencies.TargetQuery`
  for query strings and `TargetFields` for bodies, and refuse anything that
  is not one shape with a 422.
* The migration has no test of its own, as none before it does. It was
  applied to the dev database: 2 custom roles with a JD became postings of
  their own, with their 14 requirements, fits and a finished run, and 1 plan,
  1 résumé and 1 question set followed them.

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
**Done** (ADR 0031, migration 0026). Where the build differs from the plan
below:

* The outcome for a candidate with fewer openings than a role needs is
  `too_few_openings`, not `no_openings`: one with one or two openings is not
  without openings.
* `GET /role-candidates` reads each candidate's newest placement, from
  whichever build placed it, rather than only the latest `ready` build's. A
  build that found nothing in scope places nobody, so the build before it
  still speaks for its candidates, as the candidate's own columns did.
* `recluster` takes the build it is the work of, so the placements hang off
  it; tests that call it record a build first.
* On the dev database, migration 0026 placed 20 candidates: 10 `placed`,
  3 `outside_top_k` and 7 `too_few_openings`.

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
**Done** (migration 0027). As planned: the digest covers the requirements in
the order they are sent (weightiest first, then by statement) and the fit
prompt's `version_id`. Fits taken before the column have no digest, so each is
scored once more. The fits are compared through `RoleFit.is_current` and
`PostingRequirementFit.is_current`, and `compute_fits` logs
`rolemap.fits_reused`.

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
**Done** (ADR 0032, migration 0028). Where the build differs from the plan
below:

* The rule is two functions, named by the domain's prefix rule:
  `get_requirement_relevance` (the centred similarities) and
  `get_opening_fit` (the reweighting and the evaluation), not
  `fit_for_opening`.
* A dimension's gaps count by `SkillGap.weight`, the share of its
  requirements' weight the opening kept, so `evaluate` and `closing_lifts`
  take a weight; a role's are all 1, as before.
* Each build replaces a role's openings' fits as a set rather than adding a
  row per opening per build, since they are a cache.
* `one_per_company` is a query parameter. Unset, it holds across all roles
  and not for one role, as before; the SPA asks for it on the selected role.
* An opening the crawler has not embedded yet is embedded in the worker, as
  a build does; one that has left the market drops out when the list is read.

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

# Phase 9
A posting of the user's own belongs to Target, and nothing spends the user's
key unless the user asks for that spend.
* A posting of the user's own is kept, read and evaluated in `target`
  (ADR 0033), uploaded or filled in, and evaluated only when it is set as
  the target (ADR 0034).
* A gap plan or a tailored résumé is written again only when the user asks.
  When what it read has changed since, the Advisor says it is outdated, and
  regenerating it is a cost the user confirms, like an analysis or a
  rebuild.
* A plan can cite what the user answered in Fill the gap, for every gap
  the answer was about, including a requirement nothing else covers.
* Every prompt reads a fact with its date, so recent work counts for more
  than old work, and a newer fact wins over an older one it contradicts.
* The exported PDF looks like the résumé previewed, and Export downloads it
  with no link to click.
* A user chooses a résumé's sections: removes one they do not want, such
  as skills, adds one, such as side projects, filled from their sources,
  and orders them.
* A user can design a résumé template of their own, from fixed layouts,
  bundled fonts and checked colours, or start one from another résumé's PDF,
  whose style is read and whose text is kept nowhere.
* The Advisor's short AI jobs (questions, a gap plan, a résumé, a section)
  run in the background: the page stays usable, the tab being generated
  shows a spinner, and each job shows its progress and can be cancelled.
* The Advisor's pages follow the prototype of 3 October 2026 (evening): fit
  bars on the gap plan, evidence collapsed until asked for, and the
  Résumé's columns rearranged around the Sections panel.

Eleven branches, in this order. The first two were built under
`epic/no-ticket/own-posting-target`, which is already in mainline. The
other nine are cut from `epic/<ticket>/phase-9`, which is cut from mainline:

1. "A posting of your own belongs to Target": done (ADR 0033).
2. "Uploaded or filled in, evaluated when set as the target": done
   (ADR 0034).
3. "Regenerate the plan and résumé only when asked": submitting answers in
   Fill the gap stops rewriting them.
4. "A plan cites what you answered": a gap the user answered about can cite
   that answer, including a requirement with no other evidence.
5. "Read each fact with its date": every prompt that reads evidence sees
   when each fact is from, and is told what to do when facts conflict.
6. "Export what you previewed": the PDF and the preview share fonts, sizes,
   trimming and colours, and Export downloads the file itself.
7. "Sections you choose": a résumé is an ordered list of sections, which
   the user adds, removes and moves.
8. "Templates of your own": a template is a checked style spec, and a user
   can design their own from a built-in one.
9. "Start a template from a file": an uploaded PDF's style is read
   locally into a draft spec the user reviews in the editor.
10. "Advisor jobs run in the background": a short AI job never takes over
    the Advisor; it shows its stage and can be cancelled.
11. "The Advisor as prototyped": the gap plan, the résumé and Fill the gap
    take the prototype's layout.

The definition of done is Phase 5's: tests in the right tier, every gate
passing with nothing skipped, an ADR each with the index, and `CLAUDE.md`,
`README.md` and `docs/architecture.md` saying what is built.

## A posting of your own belongs to Target
**Done** (ADR 0033, migration 0030). The `target` schema holds the posting,
its evaluation runs, its requirements and their fits. `market` keeps no
pasted JDs. The fit rules stay in `rolemap` as a stateless kit.

## Uploaded or filled in, evaluated when set as the target
**Done** (ADR 0034, migrations 0031 and 0032). Adding a posting spends
nothing. "Set as target" is priced, then queues the evaluation, then opens
Fill the gap.

## Regenerate the plan and résumé only when asked
**Done** (ADR 0035, migration 0033). Where the build differs from the plan
below:

* Outdated is decided in one place, `TargetService.get_outdated_reasons`,
  which both `gapplan` and `resume` call with the basis they recorded and the
  profile version now. A Target that cannot be resolved counts as changed.
* The digest ignores the order the requirements come in, as the tests asked,
  so it hashes them sorted rather than "in order".
* Regenerating a résumé already being written answers 409.
* `latest_for` went with the submit estimate, its only caller.
* The migration has no test of its own, as none before it does.

Since ADR 0023, submitting answers in Fill the gap records them as evidence
and emits `GapAnswersSubmitted`. The dispatcher then queues
`gapplan.regenerate` and `resume.regenerate`, and each rewrites the Target's
plan or résumé on the user's key if one exists. The price is shown next to
Submit (`GET /gap-question-sets/{id}/submit-estimate`). This causes three
problems:
* Answering a question is itself a spend. A user cannot answer now and
  rewrite later, or answer a second set first and rewrite once.
* It is the only spend in the journey that the user does not ask for
  explicitly. An analysis, a role-map build, setting a posting of your own as
  the target, and writing questions are each confirmed on their own.
* Answers are not the only thing that can change what a plan or résumé
  reads. A sync, a résumé upload, a re-analysis or a rebuild changes it too,
  and none of these rewrites anything or says anything.

So nothing is rewritten automatically. Each plan and résumé records what it
read. When that has changed, the Advisor says the plan or résumé is outdated
and offers to regenerate it, at a price shown first.

Its own branch, `feature/<ticket>/regenerate-on-request`.

1. **Submitting spends nothing.**
   * `GapAnswersSubmitted` is still recorded, but the dispatcher queues
     nothing for it. It is like `TargetLocationsChanged`, which builds
     nothing (ADR 0027).
   * Delete these:
     * the `gapplan.regenerate` and `resume.regenerate` tasks;
     * the services' `regenerate`;
     * `GET /gap-question-sets/{id}/submit-estimate`;
     * `SubmitEstimate`.
   * `VersionSource.ANSWERS` stays only for versions written before this
     change.
2. **A draft records what it read.**
   * A draft reads two things, and both are recorded:
     * `profile_version`: from the `ProfileSnapshot` the draft read.
     * `target_digest`: from `get_target_digest(TargetSnapshot)`, a pure
       function in `target.domain`. It hashes the requirements in order
       (statement, weight and expected level), the basis, the fit score, the
       dimension gaps and the uncovered requirements. It leaves out
       `taken_at` and the label.
   * The two values are a `DraftBasis` value object in `target.domain`,
     exported from `target`'s `__init__.py`. Both `gapplan` and `resume`
     already depend on `target`.
   * `GapPlan` stores the `DraftBasis` when its draft finishes.
     `TailoredResume` stores it on every generate.
   * A manual edit or an applied revision reads neither snapshot, so it
     leaves the recorded basis alone.
   * Migration 0033 adds two nullable columns each to `gapplan.plan` and
     `resume.resume`. Rows from before it have no basis. They count as
     unknown, never as outdated.
3. **Outdated is worked out on read, and spends nothing.**
   * `PlanView` and `ResumeView` already take a fresh Target snapshot for
     the fit today. They now also read the profile version.
     `DraftBasis.outdated_by(current)` returns `evidence`, `target`, both or
     neither.
   * Only a ready plan or résumé is judged. For a plan, only the Target's
     latest version is judged; older versions are history.
   * The views and the schemas carry `is_outdated` and
     `outdated_by: list[OutdatedReason]`, then `make gen-client`.
   * The Target snapshot can be unusable, for example when the role has not
     been scored since a rebuild. Then the plan or résumé is outdated by
     `target`, as it is when the fit changes.
4. **Regenerating is a request with a confirmed cost.**
   * A plan already regenerates as a new version through `POST /gap-plans`,
     priced by `/gap-plans/cost-estimate`. Finished tasks carry over.
   * A résumé gets `POST /tailored-resumes/{id}/regenerate` (202), priced by
     `/tailored-resumes/cost-estimate`. It redrafts the same résumé and
     queues `resume.generate`, which saves the result as its next version
     with source `generated`.
5. **The SPA.**
   * Fill the gap's Submit shows no cost and asks for no confirmation. After
     a submit, the page says the answers are saved as evidence. It says the
     Target's plan and résumé use them once regenerated.
   * The Advisor's plan and résumé tabs show "Outdated: your evidence
     changed" or "Outdated: the target changed" (or both). The banner has a
     Regenerate button that prices the rewrite in `CostConfirm`.
   * The plan's existing "regenerate" link stays, for rewriting a plan that
     is up to date.
6. **An ADR** (0035) amends ADR 0023's "One submit" decision: submitting
   records evidence and rewrites nothing. Update the index, `CLAUDE.md`'s
   Fill the gap bullet, `README.md`, `docs/architecture.md`,
   `docs/domain_model.md` and `docs/technical/task-queue.md` to match.

Tests:
* Unit:
  * a submitted set queues no job, and the dispatcher queues nothing for
    `GapAnswersSubmitted`;
  * `get_target_digest` changes with a requirement, a weight, the basis, the
    fit score or a gap, and does not change with `taken_at` or the order the
    requirements were loaded in;
  * `DraftBasis.outdated_by` returns each reason, both reasons, and none,
    and treats a missing basis as unknown;
  * a plan or résumé is outdated by `evidence` after `record_answers`, and
    by `target` after a new fit;
  * a manual résumé edit keeps its basis;
  * regenerating a résumé saves a new version with the new basis.
* Integration:
  * submitting answers leaves the plan and résumé untouched, and both read
    as outdated by `evidence`;
  * `POST /tailored-resumes/{id}/regenerate` queues a generate under
    row-level security, and someone else's résumé answers 404;
  * migration 0033 upgrades and downgrades, and old rows read as not
    outdated.
* SPA:
  * Submit makes no estimate call;
  * the outdated banner shows its reasons;
  * Regenerate prices the rewrite before it posts.

What gets harder:
* A user who answers questions and never regenerates keeps a plan and résumé
  that ignore those answers. The banner is the only thing that tells them.
* The digest decides what counts as a change. A change to the plan or
  résumé prompt, or to the fit rules outside what the snapshot carries, does
  not mark anything outdated.
* Any evidence change marks every plan and résumé outdated by `evidence`,
  even one that does not touch this Target. Telling them apart would need
  the cited evidence, not a version number.
* Two more columns on two tables, and a profile-version read on every view
  of a plan or résumé.

Open questions:
* Whether Strengths should say the same. An assessment already records the
  profile version it read, so "Your evidence changed since this analysis"
  would cost nothing to show.

## A plan cites what you answered
**Done** (ADR 0036). As planned, with these details:

* `get_answers` sorts by when each question was answered and leaves out an
  answer whose evidence the profile no longer holds.
* `answers_by_gap` is checked in handles, before they are resolved to ids,
  since that is what the model cites.

Fill the gap asks about the Target's gaps, and each answer is stored as
`user_answer` evidence. `GapQuestion` keeps the gap it asked about
(`gap_key`) and the evidence its answer became (`evidence_id`). A plan drafted
after the answers sees them in its evidence block, because `_draft` reads the
profile again. But the answers barely reach the plan:
* **The model doesn't know which answer belongs to which gap.** Each answer
  is just another line in the evidence block ("Your answer: question —
  reply"), among every commit, issue and résumé line.
* **An uncovered requirement (`req:`) cites nothing.** `gap_plan` v1 says
  such a gap "has no evidence behind it by definition; cite nothing for
  it". So the questions Fill the gap asks about exactly these gaps can never
  be cited where they apply. The `why` can only say there is no evidence,
  next to an answer that says otherwise.
* **The rule is only in the prompt.** `assert_draft_valid` requires a
  citation on a `dim:` gap but checks nothing on a `req:` gap. Any
  evidence id the user owns would pass there.

The gaps themselves still come from the fit, which comes from the last
analysis. An answer does not move a score or close a gap until the user
re-analyses, and this step does not change that.

Its own branch, `feature/<ticket>/plan-cites-answers`, after "Regenerate the
plan and résumé only when asked". That branch is what makes a plan read new
answers at all: it is outdated by `evidence`, and the user regenerates it.

1. **`gapfill` says which answers are about which gap.**
   * `GapFillService.get_answers(owner_id, ref)` reads the answered
     questions of every set for that Target. It returns `GapAnswerView`s
     (`gap_key`, `evidence_id`, `answered_at`), newest first.
   * An answer whose evidence has since been deleted is left out. That can
     only happen through a reset; answers are not tied to a source the user
     can disconnect.
   * `gapplan` already sits above `gapfill`
     (`gapplan | resume | activity → gapfill → target`). The import-linter
     contracts need no change.
2. **The prompt is told which answers go with which gap.**
   * In the gaps block, a gap with answers lists their handles:
     `- req:kubernetes — no evidence at all for: … (worth 6 fit points;
     answered in [e41], [e42])`. This works the same for `dim:` and `req:`.
   * The answers stay in the evidence block too, so that their text is
     there to read.
   * A gap the user answered no question about is shown as today.
3. **`gap_plan` v2.**
   * A `req:` gap cites only the answers listed beside it, and cites nothing
     when none are listed.
   * A `dim:` gap still cites evidence from the evidence block, the answers
     listed beside it included.
   * When an answer says the person already does what a gap asks for, the
     `why` says so and says that a re-analysis will count it. The plan does
     not have to give that gap a task: every task must still close a gap,
     but not every gap must have a task, as today.
4. **The rule is checked, not just asked for.**
   * `assert_draft_valid` gains `answers_by_gap: Mapping[str,
     frozenset[str]]`, the evidence ids answered for each gap.
   * A `req:` gap that cites anything not among its own answers is rejected
     as `PlanInvalidError`, like a gap left unexplained. A `dim:` gap keeps
     its rule.
   * `assert_citations_exist` still runs over every citation, so an answer
     deleted while the model runs is still caught.
5. **The plan shows it.** A `req:` gap's stored `evidence` lists the
   answers it cites, as a `dim:` gap's does. `GapView` and the schema
   change nothing. The SPA already shows a gap's evidence, so the plan tab
   shows "Your answer" under that requirement with no change.
6. **The estimate needs no change.** The gateway prices the rendered prompt,
   and the handles add a few tokens per answered gap.
7. **An ADR** (0036) amends ADR 0023: an answer is evidence for the gap it
   was asked about, and an uncovered requirement may cite it. Update the
   index, `docs/domain_model.md` and `CLAUDE.md`'s Fill the gap bullet.

Tests:
* Unit, `assert_draft_valid`:
  * a `req:` gap citing its own answer passes;
  * a `req:` gap citing another gap's answer, or any other evidence, is
    rejected;
  * a `req:` gap with no answers that cites nothing passes;
  * a `dim:` gap still needs a citation.
* Unit, `get_answers`:
  * only answered questions are returned, from every set for that Target
    and none from another Target's;
  * the newest come first.
* Unit, the gapplan service, with a fake gateway that records its inputs:
  * the gaps block lists each answered gap's handles;
  * a draft citing an answer on a `req:` gap stores it in that gap's
    evidence.
* Integration: submit answers, regenerate the plan, and the `req:` gap
  answered about cites the answer under row-level security. Another user's
  answers are never listed.

What gets harder:
* An answer can explain away a gap that the plan still lists, at the same
  score and worth the same fit points, until the user re-analyses. The
  `why` says so, but the ranking does not change.
* An answer cited by a plan is the user's own word, not their work. A gap
  explained by one has weaker support than one explained by a commit, and
  the plan doesn't show the difference beyond the "Your answer" label.
* A `req:` key is a slug of the requirement's statement. A rebuild that
  rewords a requirement gives it a new key, and the earlier answers are no
  longer listed beside it, though they stay in the evidence block.
* One more read of `gapfill` on every draft, and `gapplan` now needs
  `GapFillService` in its factory.

Open questions:
* Whether `resume_write` and `resume_revise` should get the same pairing,
  so a requirement's coverage can rest on an answer. Coverage is decided by
  the fit's scores, so it would show as covered only after a re-analysis.
* Whether an answer to an uncovered requirement should count toward the fit
  with no re-analysis at all: a local rule that marks the requirement
  covered at low confidence. That changes what a fit means, so it would need
  its own ADR.

## Read each fact with its date
**Done** (ADR 0037). As planned, with these details:

* The date label is a domain rule, `get_date_label`, beside `get_shown_date`
  (the date a fact is shown and ordered by); `get_evidence_line` composes it.
* `EvidenceView` carries `stated_on`, a résumé line's upload date, on the
  Sources list too, not only in the snapshot.
* `gap_plan` is v3, after step 4's v2.
* Found while building it: the evidence mapper never saved
  `resume_file_id` on an update, so a line a newer upload restated stayed
  tied to the older file in the database (only the in-memory fake moved it).
  Deleting the older résumé took such lines away. Fixed, with an integration
  test.

Today every fact carries a date, `Evidence.observed_on`:
* an `item` (one commit, one issue): when that work happened;
* a `summary` ("40 commits authored in x"): only the latest of the items it
  counts;
* a résumé line: none;
* an answer from Fill the gap: the day it was given.

The connectors use it to choose what to collect: GitHub keeps the 25 newest
commits, and Jira ranks epics by when they were last worked on (ADR 0017).
After that no prompt sees it. `skill_assessment`, `gap_plan`,
`gap_questions`, `resume_write` and `resume_revise` all get each fact as
`[handle] (source) reference: fact`, each from its own copy of
`_evidence_block`. So:
* A skill last used five years ago weighs the same as last month's work.
* Two facts that contradict each other both reach the model, with nothing
  that says which is current. Examples:
  * "Junior developer at X" on an older résumé, and "Senior engineer at X"
    on a newer one under another file name. Résumé lines are keyed by file
    name and line number, and an upload retires nothing.
  * A résumé line against what GitHub or Jira shows.
* No prompt says what to do about a conflict. The reply is checked only for
  whether a cited id exists in the user's profile, so a stale fact can be
  scored, planned on, or written into a résumé.
* `ProfileSnapshot.evidence` is sorted by source alone. Fill the gap sends
  only the first `MAX_EVIDENCE_LINES` (60), so the facts it leaves out are
  whichever sort last. That is the user's own answers (`user_answer`), not
  the oldest facts.

Its own branch, `feature/<ticket>/evidence-dates`, after "A plan cites what
you answered", whose `gap_plan` v2 it builds on.

1. **An evidence line is written once, in `profile`.** A pure
   `get_evidence_line(evidence, handle=None)`, exported from `profile`,
   replaces the five copies. It puts the date beside the source, saying what
   the date means:
   * an item, the day the work happened: `[e3] (github, 2026-08-14) …`;
   * a summary, the latest of its items: `(github, latest 2026-08-14)`;
   * a résumé line, the day its file was uploaded:
     `(resume, from a résumé uploaded 2026-05-02)`. The snapshot takes this
     from the file the line was last found in (`resume_file_id`);
   * an answer: `(user_answer, answered 2026-09-30)`;
   * a fact with no date: `(github, undated)`.

   Only the platform writes the date, so no user-written text goes into it.
2. **Newest first.** `ProfileSnapshot.evidence` is ordered by that date,
   newest first and undated last, so any cut such as Fill the gap's 60 drops
   the oldest facts. Each prompt's handles are still assigned per call.
3. **Each prompt gets a new version with a rule on time:** `skill_assessment`
   v4, `gap_plan` v3, `gap_questions` v2, `resume_write` v2, `resume_revise`
   v2. The common rules:
   * A date says when the work happened, or when the fact was stated. A
     résumé's upload date or an answer's date is the second kind, and never
     makes the work itself recent.
   * When two facts contradict each other, the newer one wins. The older one
     is not cited as current.
   * An undated fact never overrides a dated one.

   Then, prompt by prompt:
   * `skill_assessment`: recent work weighs more than old work in `score`. A
     dimension resting only on old work keeps what that work shows, and its
     `read` says how old it is. A conflict the newer fact settled is named in
     `read`. `confidence` still reflects how much evidence there is.
   * `gap_plan`: a skill shown only by old work is a refresher, not a gap
     to learn from scratch. It keeps v2's pairing of answers with gaps, and
     an answer listed beside a gap wins over an older fact on that gap.
   * `gap_questions`: when facts on a gap contradict each other, ask which
     is current rather than asking about the gap from scratch.
   * `resume_write` and `resume_revise`: never write a fact another one has
     superseded, such as an older title, as the person's current state.
4. **Nothing reruns by itself.** The journey only runs forward, and an
   analysis spends the user's key. The new rules apply from the next
   analysis, plan, question set or résumé the user asks for. A new analysis
   re-scores the fits anyway, because a fit records the `assessment_id` it
   read. A plan or résumé is not marked outdated by the new versions either:
   the `DraftBasis` from "Regenerate the plan and résumé only when asked"
   records the evidence and the Target, not the prompt.
5. **Estimates need no change.** The gateway prices the rendered prompt, so
   they rise by the dates' tokens, a few per line.
6. **No migration.** Nothing stored or public changes, and it reverts by
   loading the previous template versions.
7. **An ADR** (0037): every prompt reads a fact with its date, and a newer
   fact wins over an older one it contradicts. Update the index,
   `docs/domain_model.md` and `CLAUDE.md`.

Tests:
* Unit, `get_evidence_line`: one line for each kind of date (an item, a
  summary, a résumé line, an answer, an undated fact), with and without a
  handle.
* Unit, the snapshot:
  * it is newest first, with undated facts last;
  * a résumé line carries the upload date of the file it was last found in.
* Unit, each of the five services: it loads the new template version, and
  the evidence it sends carries the dates (a fake gateway records the
  inputs).
* Unit, Fill the gap: with more than 60 facts, the oldest are the ones left
  out, and recent answers are kept.
* Integration: the snapshot reads the résumé file's upload date under
  row-level security, and a line found again in a newer file takes the
  newer file's date.

What gets harder:
* Strengths before and after `skill_assessment` v4 are not like for like. A
  dimension can drop with no new evidence because its work has aged, and
  comparing two assessments shows a change that no new evidence caused.
* Recency is weighed by the model, not by a rule we can test. The same
  facts can score differently from one analysis to the next.
* A summary's date is only its latest item. "40 commits authored in x,
  latest 2026-08-14" looks current even when 39 of them are years old.
* A résumé's upload date is when it was stated, not when the work happened.
  An old résumé uploaded today wins over GitHub work from last year if the
  model misreads the rule.
* An answer dated today wins over an older fact that contradicts it, so a
  user can talk the analysis out of what their own sources show.
* Every prompt that reads evidence is a little longer, on the user's key.

Open questions:
* No code writes a `CareerPosition`: the résumé parser stores lines, not
  positions. So the timeline every prompt receives is "(no positions
  recorded)" and `total_experience_months` is 0. Reading positions from the
  résumé would give its lines a date the work happened, not just the day it
  was uploaded.
* Whether a new résumé should retire the lines of the older ones
  (`replaced_refs` of `resume:*`), rather than leaving the prompt to choose
  between them.
* Whether Strengths should show how old each dimension's newest cited fact
  is. That needs no AI call: it is worked out from the dates of the cited
  facts.

## Export what you previewed
**Done** (ADR 0038, migration 0034). Where the build differs from the plan
below:

* The looks live in the domain (`template_look.py`, `constants.py`), not in
  the renderer, so the service can serve them without reaching into infra.
* The TTFs are the SPA's WOFF2 files converted, with their name tables fixed:
  the web subsets name Figtree "Figtree Light", which fontconfig would not
  match to "Figtree". `backend/assets/fonts/README.md` says how.
* The page end is a thin solid line, drawn by a repeating background, not a
  dashed one.
* The download is named with an em dash ("Maya Chen — Staff Engineer.pdf");
  ruff refuses the en dash as ambiguous.
* The source notes are shown under "Show where each line came from", off by
  default, so the page lays out as it prints.

The Résumé tab shows a preview, and Export as PDF renders the saved version
on the worker's `docs` queue (ADR 0007). The two are separate renderings
that share only three colours, and those are copied by hand:
`ResumePage` in `web/src/features/Resume.tsx`, styled by `app.css`, and
`render_html` in `advisor/resume/infra/render.py`. What a user downloads is
therefore not what they saw:
* **Fonts.** The preview sets the name and job titles in Caprasimo and the
  text in Figtree, the Organic design system's fonts, which the SPA hosts
  itself (`web/src/styles/fonts/`). The PDF uses DejaVu Serif and DejaVu
  Sans, the only fonts in the worker image. The renderer fetches nothing,
  so it cannot load the web fonts. This is the difference most people see.
* **Trimming.** "Trim to one page" cuts the PDF to 3 bullets per position
  and 12 skills (`_TRIMMED_BULLETS`, `_TRIMMED_SKILLS`). The preview always
  shows everything.
* **Size.** The preview is a card of whatever width the screen gives it,
  sized in pixels (name 29px, text 13.5px). The PDF is A4 with 18/17mm
  margins, sized in points (name 22pt, text 10pt). Lines break in
  different places, and the preview never shows where a page ends.
* **Details.** The bullets are drawn differently: the preview draws its own
  dot, the PDF uses a list's `::marker`. The preview's skills heading
  says "ordered for this role" and the PDF's does not.
* **The colours are written twice:** in `_LOOKS` and in the SPA's
  `TEMPLATES`. Nothing keeps them equal.

The preview's grey source notes, the highlight on rewritten bullets and the
editing hint stay out of the PDF on purpose: a résumé sent to a company does
not carry them. Wording is not a difference: Export is disabled while there
are unsaved edits, so the PDF is the saved version on screen.

Export is also two steps. The SPA polls the export until it is `ready`, then
shows a "Download the PDF" link. That link is signed for
`SIGNED_URL_TTL_SECONDS` (300) and is not signed again after polling stops,
so it can expire before it is clicked. Every click on Export renders and
stores another PDF, even for a version already exported.

Its own branch, `feature/<ticket>/export-as-previewed`. It does not depend
on the steps before it.

1. **The PDF renderer is the source of the look, and the PDF uses the
   design system's fonts.**
   * Caprasimo and Figtree go into the worker image as local TTF files
     (`backend/assets/fonts/`, with their SIL OFL 1.1 licences), installed
     where fontconfig finds them. `render_html` names them by family, as
     the preview does. The renderer still fetches nothing: Pango finds them
     through fontconfig, not through a URL.
   * The weights are the ones the preview uses: Caprasimo 400, Figtree 400
     and 800.
   * DejaVu stays as the fallback, for letters outside the fonts' Latin
     subset.
2. **One definition of each template.**
   * `GET /resume-templates` answers `ResumeTemplatePage` (ADR 0014),
     built from `_LOOKS`: id, name, note, rule, name colour, dot colour, the
     fonts, and the trim limits.
   * The SPA's `TEMPLATES` list is deleted and the template picker and the
     preview read the endpoint.
   * A new template is then one entry in `Template` and one in `_LOOKS`.
3. **The preview is laid out as the page is.**
   * The white page is A4 in proportion. It uses `render_html`'s sizes in
     `pt`, its margins and its bullet markers, scaled to the width it is
     given, so lines break where the PDF's do.
   * A dashed line marks where each A4 page ends.
   * With "Trim to one page" on, the preview drops what the PDF drops, by
     the limits the endpoint gives. The SPA names how many bullets and
     skills were left out, outside the page.
   * The notes that are never exported (source notes, the rewritten
     highlight, "ordered for this role", the editing hint) are drawn so they
     plainly belong to the app: in the margin or outside the page, not as
     part of its layout.
4. **Export downloads the file.**
   * Clicking Export still records an export and queues it on `docs`;
     rendering stays off the request (ADR 0007). The button shows
     "Rendering…" while the SPA polls.
   * When the export is `ready`, `GET /resume-exports/{id}` signs the URL
     with `ResponseContentDisposition: attachment` and a filename
     ("<name> – <role>.pdf": ASCII with a UTF-8 `filename*`).
     `ObjectStore.signed_url` gains an optional `download_name`.
   * The SPA sends the browser to that URL at once, and the file downloads
     with the page left as it is. No link is shown. The URL is used the
     moment it is signed, so it cannot expire first.
   * A failed export still shows its error beside the button.
5. **An unchanged export is reused.**
   * An export records what it rendered: the version, the template, and
     `trim`, the one option the renderer reads.
   * Export on a version, template and trim that already have a `ready`
     export returns that export, and the file downloads at once with
     nothing rendered.
   * The template and the options are read when Export is clicked, not
     when the worker renders, so a change in between cannot mix the two.
   * Migration 0034 adds `trim` to `resume.export`. Rows from before it
     are never reused.
6. **An ADR** (0038): the PDF renderer is the source of a résumé's look,
   the fonts are bundled in the worker image, and Export downloads
   directly. Update the index and `CLAUDE.md`'s Resume Advisor paragraph.

Tests:
* Unit, `render_html`:
  * it names Caprasimo and Figtree, with DejaVu as the fallback;
  * trim drops bullets and skills past the limits;
  * each template's look matches its `_LOOKS` entry.
* Unit, render with the worker's fonts: the PDF embeds Caprasimo and
  Figtree, not DejaVu. This runs in the `test` image, which has the fonts.
* Unit, the service:
  * a second export of an unchanged version, template and trim returns the
    first and queues nothing;
  * a change to any of the three renders again;
  * the export keeps the trim it was requested with.
* Integration:
  * `GET /resume-templates` answers every template, with the trim limits;
  * a ready export's URL carries `attachment` and the filename;
  * migration 0034 upgrades and downgrades.
* SPA:
  * the template picker and the preview read `/resume-templates`;
  * with trim on, the preview shows only what the PDF keeps;
  * Export sends the browser to the signed URL when the export is ready,
    and no download link is rendered.

What gets harder:
* Close, not identical. The browser and Pango lay out text with different
  engines, so a line can still break one word apart. The page markers are
  where A4 pages end, not a promise of where the PDF breaks.
* Font files in the image: a few hundred KB. A new weight or a fuller
  character set is a change to the image, not to CSS.
* The fonts' Latin subset means a name or a bullet in another script is
  set in DejaVu, or in nothing if DejaVu lacks it (Chinese or Japanese, for
  example), in the PDF as in the preview.
* A browser that blocks a download started after a wait would leave the
  user with nothing to click. Major browsers allow a navigation to an
  attachment, but this needs checking in Safari and Firefox.
* The SPA needs one more request before it can show the template picker.

Open questions:
* Whether to offer "Preview the PDF": open the real file, rendered with
  `inline` rather than `attachment`, for anyone who wants to check the
  exact page before sending it.
* Whether to add fonts with CJK coverage (for example Noto Sans CJK) to the
  image, for résumés written in Chinese or Japanese. It would add tens of
  megabytes.
* Whether old exports should be deleted after a while. Reuse stops most new
  ones, but nothing removes what is already stored.

## Sections you choose
**Done** (ADR 0039, migration 0035). Where the build differs from the plan
below:

* A new résumé starts with summary, experience and skills only. Nothing
  writes positions to the timeline, so "GitHub work outside every position"
  is every repository; side projects are added by the user.
* Every saved version sets the plan to its own sections, so a move or a
  removal is simply a version; there is no separate plan route.
* A section being filled puts the résumé in a `filling` status, which the
  page polls; a failure leaves it `ready` with the error.
* An empty section prints nothing. The preview says so and offers "+ Add to
  …", which starts it with a line to edit.
* Removing a section with lines asks inline ("Remove its lines too") rather
  than in a dialog.
* The migration's JSON rewrite is tested both ways against Postgres on a
  literal value (`tests/integration/migrations`).

A tailored résumé always has the same three sections, in the same order:
summary, experience and skills. `ResumeContent` has a field for each, and
the write prompt, the revise prompt, the renderer and the preview all assume
those three. A user cannot:
* leave one out, such as skills, which some people would rather show
  through their work;
* add one, such as side projects, education or certifications;
* change the order, such as putting side projects ahead of skills for a
  first job.

Side projects matter most. GitHub evidence is often personal work that
belongs to no position, and today it can only be pushed into a role it was
not part of, or left out.

The prototype's Résumé screen (`prototype/screens/Resume.dc.html`, domain
spec §6.3) draws it as a **Sections** panel in the left column, between
Template and Revise with AI:
* the résumé's sections in order, each with a drag handle and Remove, and
  "New" on one just added;
* Experience marked "Required", with no Remove;
* "Add a section", which offers Education, Talks & writing, Open source,
  Certifications and Custom…;
* "New sections are filled from your sources; add or edit lines in place."

"Section" is the glossary's word (domain spec §2), so the code uses it too.

Its own branch, `feature/<ticket>/resume-sections`, after "Export what you
previewed". "Templates of your own" builds on it.

1. **A résumé is a header and an ordered list of sections.**
   * `ResumeContent` keeps `name`, `headline` and `contact`, and replaces
     `summary`, `experience` and `skills` with
     `sections: tuple[Section, ...]`, in a new `resume/domain/section.py`.
   * A `Section` has a `kind` (`SectionKind`) and the content that kind
     holds:

     | Kind | Shown as | Holds | At most |
     |---|---|---|---|
     | `summary` | Summary | text | one |
     | `experience` | Experience | entries: title, organisation, when, bullets | one, always present |
     | `side_projects` | Side projects | entries: name, link, when, bullets | one |
     | `open_source` | Open source | entries: project, link, when, bullets | one |
     | `education` | Education | entries: school, degree, when, bullets | one |
     | `talks_and_writing` | Talks & writing | entries: title, where, when, bullets | one |
     | `skills` | Skills | a list of short items | one |
     | `certifications` | Certifications | a list of short items | one |
     | `custom` | the user's title | bullets | `MAX_CUSTOM_SECTIONS` (3) |

   * Every entry kind shares one `Entry` shape, and every bullet is today's
     `Bullet`, with its citations, `origin` and `answers`.
   * A résumé has at most `MAX_SECTIONS` (9) sections. Experience can be
     moved but never removed. The limits that apply to experience and
     skills today (`MAX_ROLES`, `MAX_BULLETS_PER_ROLE`, `MAX_SKILLS`)
     apply to every section of that shape.
   * `assert_written_lines_cited`, `cited()` and `with_citations` walk every
     section. A written line cites its evidence wherever it sits, and a line
     the user wrote is `yours`, as today.
   * A link is shown as text. The renderer never fetches it or makes it a
     live link.
2. **Stored versions move to the new shape.** Migration 0035 rewrites every
   saved version's `content`, and every revision's stored `proposal`, from
   the three fields into sections, in today's order. Nothing is lost.
   `from_dict` reads only the new shape, so no code carries both.
3. **The résumé remembers its sections.**
   * `Resume.section_plan` is the kinds in order, with each custom
     section's title. Every new version is written to it, and it changes
     when the user adds, removes or moves a section.
   * A new résumé starts with summary, experience and skills, as today. If
     the evidence has GitHub work outside every position on the timeline,
     it also gets side projects.
   * Regenerating keeps the user's plan, so a removed skills section stays
     removed.
4. **The prompts write to the plan.** `resume_write` and `resume_revise`
   each get a new version, after the ones "Read each fact with its date"
   brings in. Each is given the section plan and answers in sections:
   * write only the sections in the plan, in its order;
   * a side project or open-source entry rests on evidence that belongs to
     no position, such as a repository's commits, and cites it;
   * a section the evidence does not support is left empty, never filled
     with invented lines;
   * the revise prompt may add or remove a section only when the person
     asks for it in the chat. Its proposal applies only on request, as
     today.
5. **Adding a section fills it from the sources.** "+ Education" and the
   others are priced first (`GET /tailored-resumes/{id}/sections/estimate`)
   and confirmed. Then `POST /tailored-resumes/{id}/sections` (202) adds
   the section to the plan and queues `resume.fill_section` on `ai`. That
   job writes only that section, under `resume_write`'s rules, and saves it
   as the next version. The rest of the résumé is kept as it is.
   * A section the evidence cannot fill is saved empty, and the page says
     so: "Nothing in your sources for Education yet; add lines in place."
   * Custom… asks for the title first.
   * It runs as an Advisor job ("Advisor jobs run in the background").
6. **Removing and moving are free.** Remove and the drag handle are manual
   edits, with no AI call. They save a version and update `section_plan`.
   Removing a section that has lines in it asks first, and its lines stay
   in the earlier versions. The handle also moves with the keyboard
   (Up/Down), so reordering does not need a pointer.
7. **The renderer and the preview draw sections.**
   * `render_html` and the preview walk the sections in order. Each shape
     has one way to be drawn: entries like today's positions, lists like
     today's skills, text like today's summary.
   * Trimming applies per shape: bullets per entry and items per list.
     This generalises step 6's limits, and `GET /resume-templates` serves
     them.
   * A removed section is simply absent: no heading and no space.
8. **An ADR** (0039): a résumé is an ordered list of sections the user
   chooses, Experience always among them, and every written line still
   cites evidence. Update the index, `CLAUDE.md`'s Resume Advisor
   paragraph and `docs/domain_model.md`, and run `make gen-client`.

Tests:
* Unit, the sections:
  * each kind keeps its limits, and a second section of a single-use kind
    is refused;
  * removing experience is refused;
  * a written line in a side-project or custom section cites evidence, as
    one in experience does;
  * `from_dict` and `to_dict` round-trip every kind.
* Unit, the service:
  * removing and moving a section saves a version and updates the plan,
    with no AI call (a gateway that fails on any call);
  * filling a section writes that section only and keeps every other line;
  * a section with nothing to fill it is saved empty;
  * regenerating writes only the planned sections, in their order;
  * a new résumé gets side projects only when there is evidence outside
    every position.
* Unit, `render_html`: each kind renders, a removed section leaves no
  heading, and trimming cuts each shape by its limit.
* Integration:
  * migration 0035 rewrites stored versions and proposals, and downgrades
    them back;
  * adding a section queues `resume.fill_section` under row-level
    security, and another user's résumé answers 404.
* SPA:
  * the Sections panel lists the plan, with Experience marked required;
  * Remove and the handle (mouse and keyboard) change the preview and save
    a version;
  * removing a section with lines asks first;
  * Add a section prices the fill before it posts.

What gets harder:
* Every part that reads a résumé (two prompts, the renderer, the preview,
  coverage and the chat's proposals) now walks a list of kinds instead of
  three fields. A new kind means work in all of them.
* A user can remove what the job screens for, such as skills for a role
  that lists them. Coverage shows those requirements as unanswered on the
  page, but nothing stops it.
* A custom section's title is the user's text, shown on the page and sent
  to the model. It is escaped and passed as untrusted, like the rest of
  the résumé.
* Adding a section is a spend, where the prototype's copy makes it sound
  free. The price has to be in front of the user before the click does
  anything.
* Migration 0035 rewrites JSON in place. Its downgrade has to put a résumé
  with extra sections back into three fields, so those sections are lost
  on a downgrade.

Open questions:
* Whether a side project should become a kind of evidence of its own, so
  that a repository is one fact rather than a tally of commits.
* Whether education and certifications should be read from the uploaded
  résumé when it has them, as positions might be (see "Read each fact with
  its date").

## Templates of your own
**Done** (ADR 0040, migration 0036). Where the build differs from the plan
below:
* The spec lives in `resume/domain/template_spec.py`, with the built-in specs
  beside it (`BUILT_IN_TEMPLATES`). The sizes are `name_pt`, `heading_pt` and
  `body_pt`, with one range constant each.
* The spec has a fourth colour, `rule_color`, because Plain's rule and
  bullets were never the same colour.
* The serif and the monospace are DejaVu Serif and DejaVu Sans Mono, already
  in the worker image; the SPA hosts Latin subsets of the same files.
* `GET /resume-templates/limits` gives the editor its lists and ranges. A
  résumé's template travels as one id: a built-in name or the uuid of the
  user's own.
* `wiring.models.OWNER_ZONE_TABLES` is listed referencing tables first, so a
  user's rows are purged without tripping the new foreign key.

After "Export what you previewed", a template is data: `_LOOKS` is served by
`GET /resume-templates`, and the preview and the PDF both draw from it. But
there are still two templates, a closed `Template` enum, and a check
constraint (`template IN ('organic', 'plain')`) on `resume.resume`. A user
who wants another look has no way to get one.

A template stays a set of checked values, never markup. The renderer is safe
because nothing a user supplies reaches its HTML or CSS unescaped and nothing
is fetched (ADR 0007), and that holds for a user's template too.

Its own branch, `feature/<ticket>/own-resume-templates`, after "Sections you
choose". A template styles each kind of section. Which sections a résumé
has, and in what order, is the résumé's, not the template's.

1. **A template is a `TemplateSpec`**, a value object in a new
   `resume/domain/template.py`. Each value is limited to what both the
   renderer and the preview implement:

   | Value | Allowed |
   |---|---|
   | `layout` | `single_column`, `sidebar_left`, `sidebar_right`, `header_band` |
   | `heading_font`, `body_font` | a font bundled in the worker image and the SPA (`TEMPLATE_FONTS` in `constants.py`): Caprasimo, Figtree, a serif, a monospace |
   | `accent_color`, `name_color`, `text_color` | hex colours; text and name at least 4.5:1 against white |
   | `rule` | `none`, `thin`, `thick`, in the accent colour |
   | `name_size`, `heading_size`, `body_size` | points, each within a range (`TEMPLATE_SIZE_RANGES`) |
   | `sidebar_kinds` | for a sidebar layout, which list kinds go in the sidebar: skills, certifications, or both |
   | `heading_case` | `upper` or `as_written` |
   | `bullet` | `dot`, `dash`, `none` |

   Anything outside these is refused with a 422 naming the value. The two
   built-in looks become `TemplateSpec`s in `constants.py`, and `_LOOKS`
   goes.
2. **A user's templates are stored per user.**
   * `CustomTemplate` (`resume.custom_template`, row-level security) has a
     name and a `TemplateSpec`, stored as JSON and checked again whenever it
     is read.
   * A user keeps at most `RESUME_TEMPLATE_MAX` (default 10) templates.
   * A résumé uses either a built-in `template` or a `custom_template_id`,
     exactly one, by check constraint, the way a Target keeps one shape.
   * Migration 0036 adds the table and the column, and replaces the
     constraint.
3. **The routes.**
   * `GET /resume-templates` lists the built-in templates and then the
     user's own, each with its spec and `is_built_in`.
   * `POST /resume-templates` creates one from a spec, which the SPA starts
     from a built-in one. `PUT /resume-templates/{id}` saves it, and
     `DELETE /resume-templates/{id}` deletes it.
   * Deleting a template that résumés use moves them to `organic`. Their
     exports keep the files already rendered.
4. **The renderer and the preview implement every layout.**
   * `render_html(content, spec, options)` builds each layout from the
     spec. Every value goes into the CSS from a checked enum or a validated
     number or colour, never as text from the user.
   * The preview has the same layouts. A sidebar holds the contact line and
     the sections of the kinds the spec sends there. Every other section stays
     in the main column, which is the only one that breaks across pages.
5. **An export records the spec it rendered.** An edit to a template after
   an export must not change a stored PDF's meaning or let an outdated one
   be reused. So an export stores the spec it rendered, and reuse compares
   specs, not template ids.
6. **The SPA's editor.** Under the template picker, "Make your own" opens an
   editor on a copy of the chosen template: layout, two fonts, three
   colours, the sizes, the sidebar's sections, the heading case and the bullet.
   The preview redraws as each value changes. A colour that fails the
   contrast check is flagged, and cannot be saved.
7. **An ADR** (0040): a résumé template is a checked spec, never markup,
   and a user can keep their own. It amends ADR 0007, which kept the look
   in the renderer alone. Update the index, `CLAUDE.md`'s Resume Advisor
   paragraph and `docs/domain_model.md`.

Tests:
* Unit, `TemplateSpec`:
  * every value outside its set or range is refused;
  * a colour under 4.5:1 is refused;
  * `sidebar_kinds` naming a kind that is not a list is refused.
* Unit, `render_html`:
  * each layout renders each section once;
  * nothing from a spec appears in the CSS except checked values;
  * the built-in specs render as they did before this branch.
* Unit, the service:
  * the template limit is enforced;
  * deleting a template in use moves its résumés to `organic`;
  * an export stores the spec, and a change to the spec renders again.
* Integration:
  * the template routes under row-level security, where another user's
    template answers 404;
  * migration 0036 upgrades and downgrades, and a résumé cannot hold
    both a template and a custom template.
* SPA:
  * the editor redraws the preview;
  * a failing contrast blocks saving;
  * a deleted template leaves its résumé on Organic.

What gets harder:
* Every layout is built twice, in `render_html` and in the preview, with
  page breaks in both. A fifth layout costs more than a new colour did.
* A user can make an ugly template. The checks keep one readable, not
  good-looking.
* Fonts are what we bundle. A user who wants a particular typeface gets the
  nearest one on the list.
* Applicant-tracking systems read a sidebar's text in an order we do not
  control. The editor says so beside the sidebar layouts.

Open questions:
* Whether a template can be shared with another user, or published.
* Whether to allow a photo. It is a request, often, and a risk: an image
  in the page is a file to store and scan, and many applicant-tracking
  systems drop it.

## Start a template from a file
**Done** (ADR 0041, migration 0037). Where the build differs from the plan
below:
* The rule lives in its own concept module, `resume/domain/template_reading.py`,
  beside `TemplateReading`. Headings are short runs in capitals or a bold face,
  and only without those the sizes between body and name. The accent is the
  list markers' colour first.
* Lines and backgrounds are not read, so `rule` always defaults, and a sidebar
  starts with skills, flagged.
* The polled route is `GET /resume-template-readings/{id}`. The day-old
  clean-up is `resume.forget_template_reading`, scheduled at upload.
* `kernel.documents.open_pdf` is the shared guard: it opens a PDF under its
  page limit for the résumé parser, postings of your own and this reader.

With "Templates of your own" built, a user can design a template, but often
what they have is an example: someone else's résumé whose look they like.
Copying that design exactly is not possible, and not wanted:
* **It would undo the renderer's safety.** Turning an uploaded PDF into
  HTML or CSS of its own would let a crafted file change the layout, hide
  text, or reach the network.
* **Fonts.** A PDF embeds subsets of its fonts, often commercial ones.
  Taking them out and embedding them again is a licensing question, and
  the worker sets type only in fonts it has.
* **Someone else's data.** Another person's résumé carries their name,
  contact details and work history. None of it should be stored or shown.
* **No AI.** The AI gateway takes text only (`inputs: dict[str, str]`).
  Reading a page by eye would need image input from every provider, priced
  per image, on the user's key.

So the file's style is read locally into a draft `TemplateSpec`, and the
user reviews it in the editor before anything is saved.

Its own branch, `feature/<ticket>/template-from-file`, after "Templates of
your own".

1. **Upload.** "Start from a file" in the template editor posts a PDF to
   `POST /resume-templates/upload`. It is the own-posting path (ADR 0034):
   * the file goes to object storage, under `TEMPLATE_UPLOAD_MAX_BYTES` and
     `TEMPLATE_UPLOAD_MAX_PAGES`;
   * a `TemplateReading` run (`reading`, `ready`, `failed`;
     `resume.template_reading`, added by migration 0037) is recorded
     before `resume.read_template` is queued on `docs`, and the editor polls
     it (ADR 0006);
   * nothing is parsed in a request handler.

   PDF only: a Word file has no fixed layout to read.
2. **Reading is local and spends nothing.**
   * `resume/infra/style_reader.py` walks the first page with pypdf, which
     is already a dependency, through `kernel.documents`'s guards. It
     records each run of text: its font name, size, fill colour and
     position. It never records the text.
   * A pure rule in `resume/domain/template.py`,
     `get_template_spec_from_runs`, turns the runs into a spec:
     * the largest run is the name;
     * the most common size is the body;
     * the runs between them are headings;
     * runs that start at two different x positions across the page give a
       sidebar, and which side it is on;
     * a fill colour that is not near black is the accent.
   * Font names are mapped to the nearest bundled font by kind: serif,
     sans, display or monospace, read from the name ("Garamond", "Mono",
     "Bold").
   * Whatever cannot be read takes the Organic value, and the run lists
     which values were read and which were defaulted.
3. **Nothing of the file is kept.** The file is deleted as soon as it is
   read, whether the reading worked or not. The run keeps only the draft
   spec and the list of read values. No text, name or font name is stored
   or logged. A file that cannot be read fails with `unreadable_file`.
4. **The user reviews it.** The editor opens on the draft: "We read: a left
   sidebar, a serif heading, a teal accent", with each read value marked
   and each defaulted one flagged. Nothing is a template until it is saved,
   through `POST /resume-templates`, under the same checks. A draft that is
   never saved is deleted with its run after a day.
5. **An ADR** (0041): a template can start from someone else's résumé,
   read locally for its style only, and the file and its text are never
   kept. Update the index and `CLAUDE.md`.

Tests:
* Unit, `get_template_spec_from_runs`:
  * one-column and sidebar pages give their layouts;
  * name, heading and body sizes come out in their order;
  * font names map to the bundled fonts by kind;
  * an unreadable value falls back to Organic and is flagged;
  * every draft passes `TemplateSpec`'s checks.
* Unit, the reader: from fixture PDFs (one column, a sidebar, a scanned page
  with no text), runs come out with no text in them, and the scanned page
  fails as `unreadable_file`.
* Unit, the service:
  * the file is deleted after reading, and after a failure;
  * the run stores no text;
  * an upload over the limits is refused before it is stored.
* Integration:
  * upload, poll and save under row-level security, where another user's
    run answers 404;
  * the stored file is gone once the run is `ready`.
* SPA: the editor opens on the draft, with read and defaulted values marked.

What gets harder:
* It reads a style, not a copy. A very designed résumé, with photos, icons,
  charts or three columns, comes out as the nearest of four layouts, and the
  page has to say so before the upload, not after.
* Reading a layout from text positions is a heuristic. Some files will be
  misread, and the review step is the only thing that catches it.
* Another kind of upload to cap and test. A malformed PDF is parsed on the
  worker, as résumés and postings of your own already are.
* A user could upload a résumé they have no right to. Only its style is
  kept, so nothing of it can be shown or shared, but the upload itself still
  happens.

Open questions:
* Whether to read Word files from their styles (fonts, sizes, colours),
  without a layout.
* Whether to offer reading the page with the user's model once the gateway
  takes images, for a closer layout, priced and confirmed like any other
  spend.

## Advisor jobs run in the background
**Done** (ADR 0042, migration 0038). Where the build differs from the plan
below:
* Each component lists its own jobs (`running_jobs`) in the kernel's
  `RunningJobView`, which `advisor.activity` re-exports for the schemas; a
  posting's evaluation reports stages only, since its calls go through the
  role map's kit.
* A question set supersedes the Target's earlier ones when it is written,
  not when it is requested, so a cancelled one leaves them current.
* One job of a kind per Target at a time: a second request is a 409.
* "Set as target" prices the questions as a ceiling until the posting is
  scored (`gapfill.estimate_ceiling`), and the worker writes them after
  scoring (`wiring.queue.queue_questions`).
* A failed job shows its error on its tab as before, not in the card.

The prototype was updated on 3 October 2026 (evening): `GapsBuilding`,
`PlanBuilding`, `ResumeBuilding` and `PlanWhileResume` in
`prototype/screens/`, and the domain spec's §6.4 and §7. It calls writing
questions, drafting a gap plan and writing a résumé **Advisor jobs**: short
AI runs (under a minute) that never block the Advisor.
* While a job runs, its tab keeps the target banner and the step tabs. Its
  content area shows a slim progress card: a spinner, a title, one status
  line, a progress bar, the cost, Cancel, and links to the other tabs.
* The tab being generated shows a spinner and a word ("preparing…",
  "drafting…", "writing…") wherever the user is.
* The user can switch tabs and keep working, for example edit the gap plan
  while the résumé is written. A notice in the corner shows the running job
  ("Writing your résumé · 50% · View").
* "Target this role" and "Set as target" land on Fill the gap already
  preparing. "Generate gap plan" or "regenerate" starts a plan job, and
  "Regenerate résumé" a résumé job.

Today each of these is a job whose row its tab polls (ADR 0006): a question
set while `writing`, a plan or a résumé while `drafting`, and a posting of
the user's own while its evaluation is `running`. But:
* Each tab polls only its own row, and only while it is open. Leave the
  tab and nothing shows that the job is still running. Come back and the
  whole content area is a "Writing…" panel.
* `GET /activity`, which the shell polls for the running bar, knows syncs,
  parses, analyses and role-map builds only.
* A job has no progress, only a status, and cannot be cancelled.
* "Target this role" opens Fill the gap on a "Write questions" button; the
  questions are priced and started from there.

Its own branch, `feature/<ticket>/advisor-jobs`, after "Regenerate the plan
and résumé only when asked" and "Sections you choose", whose regenerate and
fill-section jobs it shows.

1. **`GET /activity` lists the Advisor's jobs.**
   * `Activity` gains `advisor_jobs: list[AdvisorJob]`. Each has `kind`
     (`questions`, `gap_plan`, `resume`, `section`,
     `own_posting_evaluation`), the job's id, the Target ref and its label,
     `stage`, `progress`, `started_at` and `estimated_cost_usd`.
   * The route builds the list from `gapfill`, `gapplan`, `resume` and
     `target` through their public APIs. `advisor/activity` sits beside
     `gapplan` and `resume` (`gapplan | resume | activity → gapfill`) and
     cannot read them, so the list is put together in the route.
   * The shell already polls `GET /activity` while anything runs, so every
     tab and the corner notice read one source.
2. **A job records its stage, and progress comes from it.**
   * Each job writes its `stage` to its row as it passes it. A résumé, for
     example, goes reading → writing → checking citations → saved.
     `progress` is the stage's share of the job.
   * While the model writes, and the provider streams, progress inside the
     writing stage is the output tokens so far against the template's
     `expected_output_tokens`, capped at 95% until the reply is checked.
     The gateway reports it through a callback, written to the row at most
     once every two seconds.
   * A provider that does not stream leaves the bar at the writing stage's
     start, with the spinner moving. Nothing invents a percentage.
3. **Cancel.**
   * `POST /gap-question-sets/{id}/cancel`, `/gap-plans/{id}/cancel`,
     `/tailored-resumes/{id}/cancel` and `/own-postings/{id}/cancel` mark a
     running job `cancelled`.
   * The worker checks for `cancelled` before each model call and before it
     saves, and stops there. A call already sent cannot be recalled: the
     provider charges for it, the ledger records it, and the card says so
     ("Stops before the next call; one already sent is still charged").
   * A cancelled plan version, résumé draft or question set is not shown
     in history. The version before it stays current.
   * Migration 0038 adds `stage`, `progress` and the `cancelled` status to
     the four rows.
4. **The SPA.**
   * `AdvisorJobCard` replaces each tab's "Writing…" panel: spinner, title,
     status line, bar, cost, Cancel, and links to the other two tabs.
   * The step tabs show a spinner and "preparing…", "drafting…" or
     "writing…" for any job of theirs in `advisor_jobs`, on whichever tab
     is open.
   * `AdvisorJobNotice`, in the corner on every Advisor tab other than the
     job's own, shows "Writing your résumé · 50% · View".
   * A tab whose job finishes swaps the card for its result without a
     reload. A job that fails shows its error in the card, with Try again.
   * The other tabs stay fully usable while a job runs. A tab never starts
     a second job of the same kind for the same Target while one is
     running.
5. **Targeting starts the questions.**
   * "Target this role" on the role map, and "Set as target" on Your own
     role, price writing the questions first (with the evaluation, for a
     posting of the user's own). They start the job only when the user
     confirms, and open Fill the gap preparing.
   * For a posting of the user's own, `target.evaluate_own_posting` queues
     `gapfill.write` when it finishes, so one confirmation covers both.
   * Every AI action still shows its cost before it runs (domain spec §7).
     The prototype's "About 6 calls on your key" is shown as the estimate in
     dollars, as everywhere else.
6. **An ADR** (0042): Advisor jobs run in the background with recorded
   stages, and can be cancelled before their next call. Update the index,
   `CLAUDE.md`'s Phase 2 paragraph (a drafting plan is no longer a page the
   user waits on) and `docs/technical/task-queue.md`.

Tests:
* Unit:
  * each job writes its stages in order, and its progress never goes
    backwards;
  * progress from streamed tokens is capped at 95%, and a provider that
    does not stream leaves it at the stage's start;
  * a job cancelled before a call makes no call, and one cancelled after
    the call saves nothing;
  * a cancelled version is left out of history, and the one before it is
    current;
  * an own posting's finished evaluation queues the questions.
* Integration:
  * `GET /activity` lists each running Advisor job with its Target, under
    row-level security, and never another user's;
  * each cancel route answers 404 for another user's job and 409 for a
    finished one;
  * migration 0038 upgrades and downgrades.
* SPA:
  * the tab spinner shows on every tab while a job runs;
  * the corner notice shows on the other tabs and opens the job's tab;
  * the gap plan stays editable while the résumé is written;
  * Cancel posts and the card goes;
  * "Target this role" prices the questions and opens Fill the gap
    preparing.

What gets harder:
* `GET /activity` now reads four more components, on every poll while
  anything runs.
* Cancelling is not a refund. A user who cancels during the model's reply
  pays for it and gets nothing. The card has to say that before the click.
* Progress is honest only with a streaming provider. Without one, the bar
  waits at a stage, which looks stuck for the length of the call.
* Two jobs for one Target can run at once (a plan and a résumé). They read
  the same evidence but never write each other's rows. If both start with
  the same outdated basis, both end up outdated in the same way.

Open questions:
* Whether the prototype's "Preview the result" link on the building screens
  is a design-tool shortcut or a feature: showing the previous version
  while the new one is written.

## The Advisor as prototyped
**Done** (no ADR: presentation only). Where the build differs from the plan
below:
* `EvidenceDisclosure` collapses the gap plan's gaps and the résumé's
  requirements panel. The résumé's per-line source notes stay behind "Show
  where each line came from", which already shows them only on demand.
* The gap bar replaces the "you vs the bar" chart on a skill gap, as the
  prototype draws it. `lift_scale` is `get_lift_scale`, in the gap plan's
  domain.
* The header's answer count is `answer_count` on the plan view: the answers
  given before the plan was drafted, read through `GapFillService.get_answers`.
* "Regenerate résumé" is priced up front, through the same cost estimate,
  so the line beneath it shows the cost in dollars.

The same prototype update changes what the Advisor's pages look like, beyond
the jobs. Matched against the SPA today:

* **Gap plan** (`Plan.dc.html`, spec §6.2):
  * each gap row has a bar for its fit points, under "+N fit pts";
  * its evidence is collapsed behind "Show evidence (n)", or "Show
    evidence (none found)" for a requirement with none;
  * the intro reads "Ranked by how much each moves your fit score. The bar
    shows the fit points out of 10. Open a gap to see the work it was read
    from.";
  * "Generate gap plan" and "regenerate" start a plan job. Today
    `GapPlan.tsx` lists every gap's evidence inline, with no bar.
* **Résumé** (`Resume.dc.html`, spec §6.3):
  * the "Write for" card carries "Regenerate résumé", with "Last generated
    27 Sep 2026 · cost · saved as a new version" beneath it;
  * the left column is, top to bottom: Saved résumés → Template (with
    Export PDF) → Sections → Revise with AI. The chat moves there from the
    right;
  * the right column is the requirements → evidence panel. Each row shows
    its status (Covered / Partial / Gap) and the requirement, with the
    evidence behind "Evidence ▾", collapsed;
  * the page's hint reads "Click any line to edit it in place.", and "Save
    as vN" sits under the page.
* **Fill the gap** (`GapsBuilding.dc.html`): preparing is the job card from
  "Advisor jobs run in the background", not a page of its own.
* **Everywhere** (spec §7): "Evidence is detail: show it collapsed, expanded
  on demand."

Its own branch, `feature/<ticket>/advisor-as-prototyped`, after "Advisor jobs
run in the background". It changes the SPA only, apart from one value the
bars need.

1. **A shared `EvidenceDisclosure`.** A `<details>`-based component with the
   label "Show evidence (n)", or "Evidence ▾" in the compact rows, and "none
   found" when empty. It is used by the gap plan's gaps, the résumé's
   requirements panel and the résumé's source notes, so evidence is
   collapsed the same way everywhere. Its state is not remembered between
   visits.
2. **Fit bars on the gap plan.**
   * A gap's lift is in fit points out of 100, and can be above 10. The
     prototype's "out of 10" holds only while every lift is at most 10. So
     the bar's scale is the larger of 10 and the plan's largest lift,
     returned as `lift_scale` on the plan view, and the intro names that
     scale.
   * Each bar has `role="img"` and an `aria-label` ("Closing this gap adds 9
     of 10 possible fit points"), as in the prototype.
3. **The Résumé's columns.**
   * The left column is Saved résumés → Template + Export PDF → Sections →
     Revise with AI.
   * The middle is the page with "Save as vN" under it.
   * The right column is the requirements panel, collapsed.
   * At narrow widths the columns stack in that order, the page first.
   * "Regenerate résumé" and its last-generated line sit on the Write-for
     card. Before a résumé exists it reads "Write résumé for …", as today.
4. **The gap plan's header line** reads "Drafted by <model> for <target> ·
   <fit>% fit today · uses your N answers from Fill the gap · regenerate".
   N is counted from the answers its draft read, so it is honest after
   "Regenerate the plan and résumé only when asked".
5. **Copy.** Every string above is taken word for word from the prototype,
   except where the plan has to say something the prototype does not:
   * cost in dollars rather than calls;
   * the scale of the bar.
6. **No ADR.** It changes presentation only, which is reversible and
   style-level, so it is not recorded as a decision. The prototype and its
   domain spec are the record.

Tests:
* SPA:
  * gap evidence and requirement evidence are collapsed until opened, and
    a gap with none says "none found";
  * the bar's width is the lift over `lift_scale`, and its label names
    both;
  * the Résumé's left column is in the prototype's order, with the chat in
    it;
  * "Regenerate résumé" is on the Write-for card once a résumé exists.
* Unit: `lift_scale` is 10 for a plan whose lifts are all at most 10, and
  the largest lift otherwise.

What gets harder:
* Collapsed evidence is one more click to check a claim, and every claim is
  meant to be traceable (domain spec §7). The count in "Show evidence (n)"
  is what tells a user that the claim has evidence before they open it.
* A bar scaled to the plan's largest lift is relative: two plans' bars do
  not compare, which the number beside each still allows.
* Moving the chat to the left column makes the left column the longest on
  the page. On a short screen, Revise with AI is below the fold.

# Phase 10
A tailored résumé is written from the user's sources, whether or not they
uploaded one, and what they answer in Fill the gap reaches it.
* Every section is written from the evidence: GitHub, Jira, an uploaded
  résumé and the user's answers. A user with no résumé still gets an
  Experience section, and every other section the evidence supports.
* Generating a résumé writes every section at once. Only the default ones
  (summary, experience, skills) are shown on the page; the rest wait,
  already written, for the user to show. Showing or hiding a section spends
  nothing, and each section keeps whether it is shown.
* A tailored résumé can claim a requirement it would otherwise leave out
  as a gap, when the user answered a question about that gap, and only from
  those answers.
* The Résumé's requirements panel shows which requirements rest on the
  user's own answers.
* The career timeline is recorded: each analysis reads the positions the
  user's résumé and answers state, so the résumé writer and the next
  analysis know their roles, employers and years of experience.

Three branches, in this order, each cut from `epic/<ticket>/phase-10`, which
is cut from mainline:

1. "Every section, written at once from the sources": the writer no longer
   needs an uploaded résumé to fill a section, writes them all, and the
   user shows or hides each.
2. "A résumé cites what you answered": a requirement the user answered
   about can be written from that answer, including one with no other
   evidence.
3. "Record the career timeline": the analysis reports the positions the
   evidence states, and they are stored as the profile's timeline.

The definition of done is Phase 5's: tests in the right tier, every gate
passing with nothing skipped, an ADR each with the index, and `CLAUDE.md`,
`README.md` and `docs/architecture.md` saying what is built.

## Every section, written at once from the sources
**Done** (ADR 0043, migration 0039). As planned, with these details:

* `SectionSlot.is_shown` takes no part in equality, so a slot finds its
  section shown or hidden. `get_full_plan` appends the kinds a plan lacks; the
  view, every saved plan and a cancel all hold every kind.
* "Fill from your sources" is offered on any empty section, not only on one
  that predates this branch: nothing records which is which, and the price is
  shown first.
* `expected_output_tokens` is 6,000 for both prompts, set from the reply's
  shape; it was not measured on real profiles (no live model here).

A user who connected GitHub and Jira but uploaded no résumé gets a résumé
with an empty Experience section. Three things add up to that:
* **Nothing ever writes the career timeline.** `profile.career_position`
  has a repository, a mapper and three readers (the résumé writer, the
  analysis and Sources), and no writer: `resume_parser` turns a résumé into
  evidence lines only, and no connector records a position. ADR 0039 noted
  it. So `timeline` is always "(no positions recorded)".
* **The writer is given roles only through the uploaded résumé.**
  `resume_write` v3 defines an experience entry as "one per role", `title`
  the role and `org` the employer, and says "Write only what the evidence
  shows" and "A section the evidence does not support is left empty".
  GitHub and Jira show the work but never a job title, so without
  `base_resume` the model obeys and leaves Experience empty. Every other
  section leans on the résumé the same way: education, certifications and
  talks are rarely in GitHub or Jira at all, and nothing tells the model how
  to tell a side project from open source or from paid work.
* **Only the plan's sections are written.** A new résumé's plan is
  `DEFAULT_PLAN` (summary, experience, skills). Any other section is a
  priced `resume.fill_section` job of its own, one at a time, so a user
  with only GitHub work never sees it land in Open source or Side projects
  unless they think to add those.

Its own branch, `feature/<ticket>/all-sections-from-sources`.

1. **Each kind says how it is written from evidence alone** (`resume_write`
   v4). With a timeline or an uploaded résumé, roles come from them, as
   today. Without, each kind has its rule:
   * `experience`: one entry per place the work was done, as the evidence
     names it — a Jira site, a GitHub organisation. `org` is that name;
     `title` is a job title only when the evidence states one, and
     otherwise names the work ("Payments platform, backend"), never an
     invented title; `when` runs from the oldest to the newest fact cited.
   * `open_source`: work in repositories owned by someone other than the
     user and other than an organisation they work in; `side_projects`:
     repositories under the user's own account that belong to no
     experience entry. Every repository's work lands in exactly one of
     experience, open source and side projects.
   * `skills`: what the cited work uses, ordered by what the job screens
     for when asked to; `summary`: two or three sentences over the rest.
   * `education`, `certifications`, `talks_and_writing`: only what the
     evidence states, which without a résumé is usually only the user's
     answers. Empty otherwise.
   * To tell the user's own repositories from others', the prompt is given
     the connected accounts: `SourceConnection.external_account` for each
     source (the GitHub login, the Jira site), through a new
     `ProfileSnapshot.accounts`. It is untrusted like the evidence.
2. **Generating writes every section.**
   * A write fills every built-in kind, and every custom section the résumé
     has, in one call: `_generate` passes the full list, and the reply's
     schema asks for each. A section the evidence does not support comes
     back empty, as today.
   * `expected_output_tokens` rises with the extra sections, so the estimate
     a user confirms before Generate and Regenerate rises too. Measure on
     the fixture profiles and set it from that, not a guess.
   * `resume_section` v1 stays, for two cases only: filling a custom
     section the user just added, and filling an empty built-in section of a
     résumé written before this branch. Both stay priced.
3. **Each section stores whether it is shown.**
   * `SectionSlot` gains `is_shown`, so `Resume.section_plan` is every
     section in its order with its state, and each saved version's sections
     carry it too, so going back to a version brings back what it showed.
   * A new résumé shows `DEFAULT_PLAN` and hides the rest, in
     `HEADINGS` order after them. Experience is always shown;
     `assert_plan_valid` refuses hiding it.
   * Showing and hiding are edits saved as a version, like moving a
     section: no AI call, no spend, nothing queued. A hidden section keeps
     its content, so showing it again shows what was written.
   * `MAX_SECTIONS` stops limiting what a résumé holds — that is the eight
     built-in kinds plus `MAX_CUSTOM_SECTIONS` — and limits only what is
     shown.
   * Regenerating rewrites every section and keeps each one's order and
     state. A hidden section is still rewritten, so showing it later shows
     a section written to the same evidence as the rest.
4. **Only what is shown is printed.** `render_html`, the preview and the
   export's reuse check read shown sections only. A hidden section is
   never sent to a template or trimmed. Coverage is unaffected: it is
   decided by scores, not by the page.
5. **Revise sees every section.** `resume_revise` v4 is given the hidden
   sections too, marked hidden, may rewrite them when asked, and shows or
   hides one only when the person asks, as it adds or removes one today.
6. **The Sections panel lists every section.** Each row shows its heading,
   whether it is shown, and whether it is empty ("Nothing in your sources
   for this yet"). Show and Hide replace Add and Remove for the built-in
   kinds and cost nothing. "Fill from your sources", priced, appears on an
   empty one only when it predates this branch. Adding a custom section is
   as today.
7. **Migration 0039.** Every stored `section_plan` and every saved
   version's sections gain `is_shown`: the sections a résumé has now are
   shown, and the missing built-in kinds are appended hidden and empty.
   `from_dict` reads only the new shape. The downgrade drops hidden
   sections and the flag.
8. **An ADR** (0043) amends ADR 0039: a résumé holds every section, each
   shown or hidden, and generating writes them all; adding a built-in
   section is no longer a spend. Update the index, `docs/domain_model.md`
   and `CLAUDE.md`'s "Sections you choose" bullet.

Tests:
* Unit, `section.py`:
  * a new résumé's plan holds every built-in kind, with only the defaults
    shown;
  * hiding Experience is refused; hiding and showing anything else passes;
  * the shown limit counts shown sections only.
* Unit, `get_planned` and the renderer: hidden sections are kept in the
  content and never printed; an empty shown section prints nothing, as
  today.
* Unit, the resume service, with a fake gateway that records its inputs:
  * a write asks for every section and passes the connected accounts;
  * a write with no timeline and no résumé saves the experience entries the
    reply holds, cited;
  * regenerating keeps each section's order and state;
  * showing a section saves a version and calls nothing.
* Integration: generate for a user with GitHub evidence only, and every
  section is stored, Experience and the defaults shown, the rest hidden;
  show Open source, and the next version shows it with no job queued.
  Migration 0039 upgrades and downgrades a stored résumé.
* SPA: the Sections panel shows every section with its state; Show and
  Hide save without a price; "Fill from your sources" shows only on an
  empty section of an older résumé.

What gets harder:
* Every write costs more, for sections most users never show. A user who
  only ever wants the defaults pays for the rest each time they regenerate.
* An experience entry without a timeline or a résumé names a place and the
  work, not a job title. That reads thinner than a résumé the user wrote,
  and the prompt rule against inventing a title is only in the prompt.
* Telling open source from side projects from paid work rests on repository
  owners and the accounts given. An organisation's repository the user
  contributed to as an outsider reads as experience.
* A hidden section is still content: the revise chat and every reader of a
  version walk it.
* Migration 0039 rewrites stored JSON again, as 0035 did.

Open questions:
* The career timeline stays empty until "Record the career timeline". Until
  then these rules are the only way Experience is written without a résumé,
  and they stay the rule for a user whose evidence states no position.
* Whether a section the evidence left empty should be shown as an empty
  row in the panel, or listed apart as "nothing to write".

## A résumé cites what you answered
**Done** (ADR 0044). As planned, with these details:

* A requirement's answers are those under its dimension's key or under its
  own statement's, since a requirement mapped to a dimension with no bar is
  asked about by its statement.
* The check also runs on a filled section, and `get_claims_settled` clears an
  `answers` naming no requirement before it.
* The rows stored on the résumé carry the answers, so a revision sees the
  pairing of its last write.
* Amended by ADR 0046 after the first real résumé failed: a claim nothing
  backs is now dropped from its line, not the whole write rejected.

Phase 9's "A plan cites what you answered" left this as an open question.
The answers do reach the résumé today, but they cannot help it where they
matter most:
* **The writer sees every answer.** `_generate` reads
  `profile.snapshot`, which holds every fact, so each answer is a line in
  the evidence block (`[E7] (user_answer, answered 2026-…) …`), and the
  model may cite it.
* **But the coverage list forbids the gaps.** `resume_write` v3 says "Do
  not claim a requirement marked "gap"". Coverage comes from
  `resume.domain.coverage`, which judges each requirement by the latest
  analysis's dimension score against the Target's bar. Fill the gap asks
  only about gaps, so its answers are about exactly the requirements the
  writer is told to leave out.
* **The model does not know which answer belongs to which requirement.**
  As in the plan before ADR 0036, an answer is just another line among
  every commit, issue and résumé line.
* **The rule is only in the prompt.** Nothing checks a bullet's
  `answers` (the requirement it claims) against its verdict, so a bullet
  may claim a gap from any evidence the user owns, and a bullet that obeys
  the prompt cannot use the answer meant for it.

Coverage itself still comes from the last analysis. An answer does not move
a score or turn a gap into covered until the user re-analyses, and this step
does not change that.

Its own branch, `feature/<ticket>/resume-cites-answers`, after "Every
section, written at once from the sources". A résumé written
before the answers is already outdated by `evidence` (ADR 0035), so
Regenerate is what makes it read them; nothing new is queued.

1. **Each coverage row knows its gap.**
   * A row's gap key is the one Fill the gap asked about:
     `gap_key_for_dimension(dimension_key)` for a requirement mapped to a
     dimension, `gap_key_for_uncovered(statement)` for one mapped to
     nothing. Both live in `target.domain`; `target/__init__.py` exports
     them, since `resume` may import only a component's public surface.
   * `ResumeService` takes `GapFillService` in its factory and calls
     `gapfill.get_answers(owner_id, ref)` once per write. `resume` already
     sits above `gapfill` (`gapplan | resume | activity → gapfill →
     target`); the import-linter contracts need no change.
   * `Coverage` and `CoverageView` gain `answer_ids` / `answers`: the
     evidence the user's answers to that row's gap became, newest first.
     A `dim:` answer is listed under every requirement mapped to that
     dimension.
   * The rows are stored on the résumé as today (`resume.coverage`, JSON),
     with the answers' ids. A row stored before this has none; no
     migration.
2. **The prompt is told which answers go with which requirement.**
   * In the coverage block, a row with answers lists their handles:
     `- gap: Runs Kubernetes in production (answered in [E41], [E42])`.
     Covered and partial rows list theirs the same way.
   * The answers stay in the evidence block too, so their text is there to
     read.
3. **`resume_write` v5 and `resume_revise` v5.**
   * A requirement marked `gap` with no answers is still not claimed.
   * A requirement marked `gap` with answers may be claimed only by bullets
     that cite those answers and nothing else. Such a bullet says what the
     answer says, in the person's own terms, and never adds a number, a
     scope or an outcome the answer does not state.
   * Covered and partial requirements keep their rule; their answers are
     ordinary evidence.
   * Revise reads the coverage stored at the last write, answers included.
     An answer given after that write makes the résumé outdated by
     `evidence`, and Regenerate, not a revision, picks it up.
   * `resume_section` v1 has no coverage and claims no requirement, so it
     is unchanged. A hidden section is written to the same rule, since it
     may be shown later.
4. **The rule is checked, not just asked for.**
   * A new domain rule, `assert_gap_claims_answered(content, coverage)`,
     runs after `assert_written_lines_cited`, on writes, revisions applied
     and saved edits alike:
     * a bullet whose `answers` names a requirement with verdict `gap` must
       cite at least one of that row's answers, and nothing outside them;
     * a bullet whose `answers` names no requirement on the list has its
       `answers` cleared rather than rejected, as a typo is not an invented
       claim.
   * A breach on a write or a proposed revision is `OutputInvalidError`,
     like a line with no citation. A manual edit is the user's own word
     and is not checked by it, the same way `mark_edits` makes the line
     `yours`.
   * `assert_citations_exist` still runs over every citation, so an answer
     deleted while the model runs is still caught.
5. **The Résumé shows it.**
   * `api/schemas/resume.py`'s `Coverage` gains `answers` (the
     `EvidenceNote`s), built in `from_view`; then `make gen-client`.
   * In the requirements panel, a `gap` row with answers shows "Answered by
     you" beside its verdict badge, and its `EvidenceDisclosure` lists the
     answers. A `gap` row without them keeps "Nothing in your sources
     speaks to this yet."
   * The verdict stays `gap`: the badge does not turn green on the user's
     word alone.
6. **The estimate needs no change.** The gateway prices the rendered
   prompt, and the handles add a few tokens per answered requirement.
7. **An ADR** (0044) amends ADR 0023 and extends ADR 0036 to the résumé: an
   answer is evidence for the gap it was asked about, and a résumé may claim
   that gap's requirement from it and nothing else. Update the index,
   `docs/domain_model.md` and `CLAUDE.md`'s Phase 9 résumé bullets.

Tests:
* Unit, `coverage`:
  * a row mapped to a dimension lists the answers to `dim:<key>`;
  * an unmapped row lists the answers to its `req:` slug;
  * a row nobody answered about lists none.
* Unit, `assert_gap_claims_answered`:
  * a bullet claiming a `gap` row and citing its own answer passes;
  * one citing another row's answer, or any other evidence, is rejected;
  * one claiming a `gap` row with no answers is rejected;
  * one claiming a covered or partial row is not affected;
  * one claiming a requirement not on the list has `answers` cleared.
* Unit, the resume service, with a fake gateway that records its inputs:
  * the coverage block lists each answered row's handles;
  * a revision whose proposal breaks the rule is refused, and the résumé is
    unchanged;
  * a manual edit claiming a gap is saved.
* Integration: submit answers, regenerate the résumé, and a bullet claiming
  the answered requirement cites the answer under row-level security.
  Another user's answers are never listed.
* SPA: a `gap` row with answers shows "Answered by you" and the answers in
  its disclosure; one without keeps the empty text.

What gets harder:
* A résumé is a document a recruiter reads, not a plan the user reads. A
  bullet written from the user's answer is their own claim, with nothing
  behind it the platform has seen; the `user_answer` evidence is the only
  trail. The rules against embellishing it are only in the prompt.
* The requirements panel can show a requirement as a gap while the page
  claims it. That is true to how coverage is decided, but it reads as a
  contradiction until the user re-analyses.
* A `req:` key is a slug of the requirement's statement. A rebuild that
  rewords a requirement gives it a new key, and the earlier answers are no
  longer listed beside it, though they stay in the evidence block.
* One more read of `gapfill` on every write, and `resume` now needs
  `GapFillService` in its factory, as `gapplan` does.

Open questions:
* Whether an answer should count toward coverage with no re-analysis: a
  local rule that turns an answered gap into `partial`. It changes what a
  verdict means and, through the fit, what the role map shows, so it would
  need its own ADR (Phase 9 left the same question for the fit).
* Whether a manual edit that claims a gap should be warned about in the
  editor rather than saved silently.

## Record the career timeline
**Done** (ADR 0045, migration 0040). As planned, with these details:

* The new column is `skill_assessment_id`, named after the entity in full as
  the design guideline requires.
* A reply that reports no positions empties the timeline, as any other
  reading replaces it.
* Its integration test needs migration 0040 on the database it runs against.

The timeline has every reader it needs and no writer (see "Every section,
written at once from the sources"):
* **The résumé writer** is given `timeline` and gets "(no positions
  recorded)" every time, so it learns roles and employers only from the
  uploaded résumé's raw text, and Experience is only as good as the model's
  reading of it.
* **The analysis** is given the timeline and "Total experience, overlaps
  counted once" (`assessment/service.py`, `_timeline_block`) to judge
  seniority, and gets nothing, even for a user who uploaded a résumé.
* **`GET /profile`** returns `positions` and `total_experience_months`,
  always empty. The SPA reads neither.

Where positions should come from:
* **Not from the résumé parser.** `resume_parser` is local and splits text
  into lines on purpose. Reading titles, employers and date ranges out of
  free-form résumés locally is unreliable.
* **Not from a model call on upload.** Uploading spends nothing today, and
  must not start spending the user's key without asking.
* **From the analysis.** It is already a confirmed spend, already reads
  every résumé line and answer, and is the first reader of the timeline.

Its own branch, `feature/<ticket>/career-timeline`, after "A résumé cites
what you answered".

1. **`skill_assessment` v5 reports the positions.**
   * The reply gains `positions`: `title`, `company`, `started_on` and
     `ended_on` (`YYYY-MM`, `ended_on` null for a current one), and
     `evidence_ids`.
   * A position is reported only when the evidence states it: a résumé
     line or an answer. It is never inferred from a GitHub organisation or
     a Jira site, which say where work happened, not what the job was.
   * The newer fact wins, as ADR 0037's rules on time already say: an answer
     that corrects a résumé's title or dates replaces it.
   * The prompt no longer gets the stored timeline. It works the positions
     out from the evidence first and judges seniority from them, so a run
     never just confirms the last run's reading.
2. **The positions are checked, not trusted.**
   * Every cited id must be the user's, and must be `resume` or
     `user_answer` evidence; any other citation rejects the whole reply, as
     an invented id does today.
   * Dates must parse, start no later than they end, and end no later than
     today. A position that breaks these rejects the reply too, so a bad
     reading never half-lands.
3. **The analysis stores them.**
   * `CareerPosition` gains `evidence_ids` and `assessment_id`.
   * `ProfileService.replace_positions(owner_id, assessment_id, positions)`
     replaces the whole timeline, in the same success path that records the
     analysis. A failed analysis leaves the last timeline as it was.
   * `assessment` already reads `profile`; the import-linter contracts need
     no change. `profile` keeps owning its table.
   * Replacing the timeline does not bump the profile version: it is a
     reading of the evidence, not new evidence. A résumé written before it
     is still outdated by `evidence` when the evidence that changed it
     arrived.
   * Migration 0040 adds both columns. Existing rows: none.
4. **The readers use it, unchanged.** `_timeline_block` and `_write_inputs`
   already format positions; `total_experience_months` already merges
   overlaps. With a timeline, `resume_write` v4's rule that roles come from
   it applies, and Experience gets real titles and employers even when the
   uploaded résumé's layout reads badly as text.
5. **Nothing new on screen.** Sources lists facts and nothing the analysis
   made of them, so the timeline does not appear there. `GET /profile`
   keeps returning it.
6. **The estimate** rises by the positions' output tokens. Set
   `expected_output_tokens` from the fixture profiles.
7. **An ADR** (0045): the career timeline is the analysis's reading of the
   evidence, cited to résumé lines and answers, replaced by each successful
   analysis. Update the index, `docs/domain_model.md` and `CLAUDE.md`.

Tests:
* Unit, the position rules:
  * a position citing a résumé line or an answer passes;
  * one citing GitHub or Jira evidence, or an id the user lacks, rejects
    the reply;
  * a start after its end, or an end in the future, rejects the reply.
* Unit, the assessment service, with a fake gateway:
  * a successful run replaces the timeline with the reply's positions;
  * a failed run leaves it as it was;
  * the prompt is not given the stored timeline.
* Integration: an analysis of a user with an uploaded résumé stores their
  positions under row-level security, `GET /profile` returns them with the
  months merged, and another user's timeline is never read.

What gets harder:
* The timeline changes only when the user re-analyses. A résumé uploaded
  after the last analysis is in the evidence the writer reads, but not in
  the timeline, until then.
* A position is a model's reading, cited but not checked against the text
  it cites. A wrong title or date reaches the résumé's Experience, and the
  user cannot correct the timeline except through an answer and a
  re-analysis.
* Every analysis spends a little more, for the positions.

Open questions:
* Whether the user should see and correct the timeline. Sources is the
  wrong place by the journey's rule; Strengths, which shows what the
  analysis made, may be the right one.

## Found while testing Phase 10
Fixed on the epic, each on its own branch:
* **A failed résumé could not be tried again.** It now has Try again, priced
  first (`bugfix/no-ticket/retry-failed-resume`, cut from mainline).
* **A gap claim the answers could not back failed the whole write.** The
  claim is dropped and the line kept (ADR 0046).
* **The left column was squeezed.** The side columns take a share of a wide
  screen, a section row keeps its name on one line, and the layout stacks
  below 1240px.
* **Titles on the page could not be edited.** Headline, contact, section
  headings, entry fields and list items now can. A built-in section may take
  a heading of its own, kept through every rewrite.
* **Fonts needed a template of one's own.** A résumé may set its two fonts
  over its template's from the Template panel (ADR 0047, migration 0041).
* **Contact details were plain text.** They are typed items drawn with icons,
  edited in place (ADR 0048, migration 0042).

# Phase 11
The 4 October prototype: the app gets its name, and the Advisor works against
a target only once the user has chosen one.
* The app is called **CareerPolaris**, with an icon: a path climbing from a
  dot (your evidence) to a star (the target role).
* No target exists until the user clicks "Target this role" on the role map,
  or "Set as target" on a role of their own. Until then the Advisor shows
  **No target yet**, with its tabs locked, and offers the role map, a role of
  their own, or a previous target.
* "Previous targets" on the target banner switches back to a role targeted
  before, restoring its answers, plan and résumé with no AI call.
* The role map lists "Openings for this role", newest first and without a
  fit per opening, because the fit is scored on the role.
* The Résumé has two columns: the tools, collapsible, beside the page.

Four branches, in this order, each cut from `epic/no-ticket/update-prototype`,
which carries the prototype:

1. "CareerPolaris": the name and icon.
2. "Openings for this role": newest first, paged, no fit per opening.
3. "No target until one is chosen": the target rule, No target yet and
   Previous targets.
4. "The Résumé in two columns".

The definition of done is Phase 5's: tests in the right tier, every gate
passing with nothing skipped, an ADR where a decision is costly to reverse,
and `CLAUDE.md`, `README.md` and `docs/architecture.md` saying what is built.

## CareerPolaris
* The sidebar and the sign-in screen show the icon and the name; the browser
  tab reads CareerPolaris, with the icon as its favicon (`web/public/icon.svg`).
  `AppIcon` draws the mark in its four colour versions.
* The API's OpenAPI title is CareerPolaris.
* The repository, the `jsa-*` images, `jsa_net` and the compose projects keep
  the old name: renaming them would break every running stack for nothing a
  user sees. No ADR, because a name is easy to change back.

## Openings for this role
ADR 0049.
* The role map's "Top matched openings" becomes "Openings for this role":
  every open posting in the selected role, newest first, ten at a time, with
  "See all n openings" paging through the rest.
* A row shows the company, the posting with its link, place, pay, credit and
  how long ago it was posted (`posted_on`: the source's day, else the first
  fetch). It shows no fit, because the fit is scored on the role.
* `GET /matched-postings` takes `order=fit|newest`; the Advisor keeps `fit`.
* No row selects an opening, so "Target this role" aims at the role only. A
  Target that names an opening, set before, still works, and opening fits are
  still computed for it.

What gets harder: a new Target can no longer name one opening from the map,
yet every build still works out opening fits.

## No target until one is chosen
ADR 0050.
* No Target exists until the user sets one: "Target this role" on the role
  map, "Set as target" on a role of their own, or a previous target used
  again. Picking a bubble only selects it.
* The sidebar's Advisor link opens the Target last set, or **No target yet**:
  the steps locked, and three cards — the role map (with its best fit), a role
  of your own, and up to three previous targets with "Use again".
* "Previous targets (n)" on the target banner lists the others, each with
  where it came from, when it was last used and its fit. Switching back
  restores its answers, plan and résumé, and posts nothing.
* The current Target and the history are kept in the browser, per account,
  and joined with the Targets the server has plans and résumés for.

What gets harder: the current Target does not follow the user to another
device, and a Target with only answers is remembered only where it was set.

## The Résumé in two columns
No ADR: a layout is easy to change back.
* The tools sit beside the page as three collapsible cards: **Layout**
  (template, fonts, options and Sections; open), **Revise with AI** (open,
  saying how many proposals wait) and **Coverage** (the requirements and
  their evidence; closed, counting covered, partial and gaps).
* "Save as vN" and "Export as PDF" sit beneath the page. The export still
  waits for unsaved edits to be saved.
* The Saved résumés panel became the **Version** list on the Write-for card:
  one entry per saved résumé, with its version and the day it was edited.
  Choosing another target's switches to that target.
* Below 1240px the page comes first and the tools follow.

Not yet: listing the older versions of one résumé. A `ResumeVersion` carries
no content and no route reads one back, so the list shows each résumé's
latest only, where the prototype shows v3 and v2 of one.

## More fonts
* A résumé or a template may set six more families: Inter and Lato (sans),
  Source Serif 4, Merriweather and EB Garamond (serif), and IBM Plex Mono —
  ten in all (`TEMPLATE_FONTS`). Each is Fontsource's Latin subset, 400 and
  700, SIL OFL 1.1: WOFF2 for the preview (`web/src/styles/fonts`), TTF in
  the worker image (`backend/assets/fonts`), so the PDF sets what the preview
  shows (ADR 0038). Merriweather's name table is rewritten so fontconfig
  finds it by name.
* Migration 0043 widens the résumé's font checks. A unit test asks
  fontconfig in the app image for every listed family by name, and another
  holds the API's `FontName` to the domain's list.

What gets harder: every family adds about 100 KB to the worker image and the
SPA, and a family a PDF names is still mapped only by kind when a template is
read from a file (ADR 0041).

## Remove one entry from a section
* Each entry on the page — a job under Experience, a repository under Side
  projects or Open source — has a round remove control (×) in the page margin
  left of its title, quiet until the entry is pointed at. Sitting in the
  margin, it moves nothing on the page that the PDF prints. It takes the whole entry off the draft; the
  entry is gone once "Save as vN" saves the version. Nothing prints it.

## Sections saved on request
* Show, Hide, moving and removing a section no longer save a version at
  once. They change the draft, as an edit on the page does, and "Save as vN"
  keeps them; until then the page says there are unsaved edits.
* "Fill from your sources" asks the user to save first while the draft has
  unsaved changes: a filled section lands in the saved version and would
  write over them.

## Undo
* "↶ Undo" beside "Save as vN" takes back the last unsaved edit to the
  résumé — a line, a heading, a removed entry, a section shown, hidden or
  moved — one at a time, up to fifty, back to the saved version. Cmd/Ctrl+Z
  does the same while no line is being typed in; a line being edited keeps
  the browser's own undo.
* Saving, or opening another résumé, starts the history again: what is saved
  is changed by editing and saving again.

# Phase 12
Hybrid deployment: the light part that is always on runs on a DigitalOcean
droplet (1 vCPU, 2 GB), and the heavy part runs on the operator's own
machine.
* **The droplet ("edge")** runs Caddy, `web`, `api` and Postgres. Every
  request reads Postgres, so it sits beside the api.
* **The operator's machine ("compute")** runs `worker` (the `ai`, `sync` and
  `docs` queues: embeddings, WeasyPrint renders, connector syncs) and
  `crawler` (the embedding model, plus parsing hostile HTML).
* **Object storage** is a DigitalOcean Spaces bucket, which both places read
  and write. A presigned link has to reach the browser from either place, and
  MinIO would not fit in the droplet's memory. MinIO stays for local
  development.
* **The link between the two places** is a private tunnel (Tailscale or
  WireGuard), opened outbound from the operator's machine. Postgres listens on
  the tunnel only, and the operator's machine opens no inbound port.

Why this split: the embedding model costs about 1 GiB in each process that
loads it (the worker and the crawler), and a PDF render spikes on top of that.
Neither fits on 2 GB beside Postgres. The api runs no embeddings: it prices
work as a ceiling (`RoleMapService`), and only imports `sentence_transformers`
lazily, so it never loads the model. Résumé chat streams from the api, so it
keeps working while the compute side is away.

Droplet budget, to confirm with `make stats` before the phase is called done:

| On the droplet | Estimate |
|---|---|
| OS, dockerd, the tunnel | about 350 MB |
| Caddy, `web` | about 50 MB |
| `api`, one uvicorn process | about 250 MB |
| Postgres, `shared_buffers` 128 MB | about 300–400 MB |
| **Total** | **about 1 GB**, half the droplet |

There is no domain yet. Until there is one, the edge is served at
`<droplet-ip>.sslip.io`, with a Let's Encrypt certificate for that name.

Five branches, in this order, each cut from `epic/no-ticket/hybrid-deploy`,
which is cut from mainline:

1. "Run the app in two places": one image and one compose file, with what
   each place starts chosen in its `.env`.
2. "Know when the compute side is away": the SPA says that work is waiting
   for the processing machine instead of reporting it lost.
3. "The edge on the droplet": the proxy, TLS, the firewall, per-IP limits,
   Spaces and backups.
4. "Limit what one account can do": per-user and per-IP quotas the proxy
   cannot see, kept in Postgres.
5. "Release one image to both places": CI builds, tests, scans and pushes the
   image; each place pulls it by digest.

There is no separate API gateway (Kong, Tyk, APISIX): it would take 100–500 MB
of the droplet and is one more thing to run. Caddy limits what it can see, a
client's address and its request, and the app limits what only it can see,
the account.

The definition of done is Phase 5's: tests in the right tier, every gate
passing with nothing skipped, an ADR where a decision is costly to reverse,
and `CLAUDE.md`, `README.md` and `docs/architecture.md` saying what is built.
`architecture.md` open question 1 (the choice of platform) gets its answer.

## Run the app in two places
**Done** (ADR 0051). Where the build differs from the plan below:

* One `PUBLISHED_BIND_ADDRESS` (default `127.0.0.1`) for every published
  port, not one per port. Postgres stays on loopback on the droplet too:
  `infra/tunnel-up.sh` has Tailscale forward the tunnel's port 5432 to it
  (`tailscale serve`). Binding the tunnel's address directly would fail at
  boot whenever Docker started Postgres before the tunnel had that address.
* The tunnel is its own profile, `tunnel`, which both deployed places name
  and development does not. MinIO is in `local`.
* That each profile starts only its services is checked with
  `docker compose config --services` for each place, not by an integration
  test: the tests run inside a container and never drive compose.
* Infra services restart with the host (`restart: unless-stopped`); without
  it a droplet reboot left Postgres down.
* Found while building it: a fresh database could not migrate past 0013,
  whose clean-up named a column today's metadata no longer has. Fixed on
  `bugfix/no-ticket/fresh-database-migrations`, since every new install, the
  droplet's among them, starts from a fresh database.

ADR: running in two places, and why each process lives where it does.
* **Compose profiles.** `compose.yaml` puts `api` and `web` in the `edge`
  profile, and `worker` and `crawler` in the `compute` profile. Each place
  sets `COMPOSE_PROFILES` in its own `.env` (`edge`, `compute`, or both for
  local development and CI), so `start-app` and `stop-app` keep their names
  and the Makefile has no site variable. `infra/compose.yml` does the same:
  Postgres in `edge`, the tunnel in both, MinIO in a `local` profile only.
* **Migrations under a lock.** `start-app` migrates first in either place.
  `cli.migrate` takes a Postgres advisory lock, so two places starting at once
  cannot race, and the second finds nothing pending. A compute site that runs
  an older image than the schema fails its start (the schema is ahead of its
  code) instead of running against it.
* **Published ports bind to an address.** Every `ports:` entry takes an
  optional `*_BIND_ADDRESS` (default `127.0.0.1`). Docker writes its own
  iptables rules ahead of `ufw`, so today `0.0.0.0:21470` exposes the api
  over plain HTTP on any host that has a public address. Postgres binds to the
  tunnel address on the droplet.
* **Postgres sized for the droplet.** `shared_buffers`, `work_mem`,
  `effective_cache_size` and `max_connections` become optional `POSTGRES_*`
  settings, passed as `-c` flags, with defaults that suit local development.
  `DB_POOL_SIZE` falls to 2–3 per process: two places now open connections to
  one server.
* **The tunnel as a container.** A pinned Tailscale (or WireGuard) image in
  infra, in both places. Its auth key is a secret in `.env`. `start-infra`
  waits until the tunnel is up and, on the compute side, until Postgres
  answers across it.
* **Integration tests** cover the migration lock (two concurrent runs, one
  applies) and that each profile starts only its services.

## Know when the compute side is away
**Done** (ADR 0052, migration 0044). Where the build differs from the plan
below:

* Procrastinate's heartbeat says whether a worker is up but not since when,
  and the crawler has no grant on the job schema. So the worker and the
  crawler each beat into `presence.process` (`kernel.presence`), from a
  thread, because the crawler's embeddings and the worker's renders block the
  event loop.
* The limit does not count from when a worker picks a run up. It counts only
  the time the worker has been up: from the later of the run's start and the
  worker's return. That is one rule in `activity` instead of a new column
  and write in every job of five components, and the user sees the same
  thing. A run waiting for the machine therefore reads as running, with
  "Waiting for the processing machine to come back" on the running bar, not
  as `queued`.
* `GET /activity` says `processing` as two booleans and two last-seen times,
  not `online | away`: the crawler and the worker can be away apart.
* The notice is in `CostConfirm`, which every priced action shares. Export,
  which is not priced, shows it only on the running bar.

ADR: work waits for the processing machine, and the stale limit counts from
when a job starts.
* **Who is online.** Procrastinate 3 records a heartbeat per worker
  (`procrastinate.procrastinate_workers`). The crawler has no grant on the job
  schema, so it writes its own heartbeat to a row in `market`. `activity`
  reads both and reports `processing: online | away`, with when each side was
  last seen, in `GET /activity`.
* **Queued is not lost.** Today a run's staleness counts from when it was
  recorded, which is before it is queued (`activity/domain/stages.py`). A run
  queued while no worker is online would read as lost after
  `JOB_STALE_AFTER_SECONDS`. Instead, staleness counts from when a worker
  picks the run up, and a run nobody has picked up reads `queued`, never
  `stale`.
* **The user is told before spending.** Analyze, Rebuild, Target this role,
  Set as target, Generate, Regenerate and Export say "Processing is offline;
  this starts when it is back" next to the estimate while the compute side is
  away. They can still confirm: the job waits in the queue, and the outbox
  waits with it.
* **The market wait.** A build waits for its sources only while the crawler
  is online. With the crawler away, `MARKET_WAIT_SECONDS` starts counting
  when it comes back, so the build is not made on a stale market just because
  the operator's machine was asleep.
* **Unit tests** for the staleness rule and the online/away read. An
  integration test queues a run with no worker online, and checks that it
  reads `queued`, not `stale`.

## The edge on the droplet
**Done** (ADR 0053). Where the build differs from the plan below:

* The proxy is an app service with a profile of its own, `proxy`, not infra:
  it is built (`proxy/`, Caddy plus `caddy-ratelimit`), and released and
  scanned like the app's images. The droplet runs `edge,proxy,tunnel`.
* Spaces needed a code change: `ObjectStore.ensure_bucket` listed every
  bucket, which a key limited to one bucket may not do. It now asks
  `HeadBucket` about its own.
* No lifecycle rule expires exports. They live under each user's prefix,
  which a rule cannot match, and an unchanged export is reused, so an
  expired file would leave a link to nothing.
* The per-address limits came into this step from "Limit what one account
  can do", as planned. They were checked against stub upstreams: the
  eleventh `/auth/*` request in a minute gets 429 with `Retry-After: 60`,
  and a body over the cap gets 413.
* The firewall, swap, SSH and the operator's machine are in `docs/deploy.md`,
  the runbook for both places. They are not code.

* **Caddy, one origin.** A pinned Caddy image in infra on the edge serves
  `/api/*` to `api` and everything else to `web`. It holds the only public
  ports, 80 and 443. `SITE_HOSTNAME` (required) is the name it gets a
  certificate for: `<droplet-ip>.sslip.io` for now. `WEB_API_BASE_URL`,
  `AUTH_PUBLIC_API_BASE_URL`, `OAUTH_REDIRECT_BASE_URL` and
  `CORS_ALLOWED_ORIGINS` are all `https://$SITE_HOSTNAME`, and
  `AUTH_COOKIE_SECURE=true`.
* **Sign-in.** Google sign-in stays off (`GOOGLE_OAUTH_CLIENT_ID` blank)
  until there is a domain of our own, because Google's consent screen wants a
  domain we can verify. The GitHub and Jira callbacks accept the sslip.io
  name.
* **Firewall.** A DigitalOcean Cloud Firewall allows 22, 80 and 443, plus the
  tunnel's UDP port if WireGuard is used. SSH takes keys only.
* **Limits at the edge, per client address.** The api has none today: the
  only limit is the sign-in lockout, which counts failures per account, so a
  flood spread over many accounts never trips it. Every `/auth/register` and
  `/auth/sign-in` runs Argon2id (19 MiB, two passes), and enough of them use
  up the one vCPU. Caddy therefore:
  * caps a request body a little above the largest upload
    (`RESUME_MAX_BYTES`), so an oversized one is refused before uvicorn reads
    it;
  * sets read, header and idle timeouts, so a slow client cannot hold one of
    uvicorn's few connections;
  * allows `/api/v1/auth/*` about 10 requests a minute per address;
  * allows everything else about 300 a minute per address. The SPA polls
    `GET /activity` every two seconds while work runs, so a tight limit here
    would lock out real users.

  Rate limiting is a Caddy plugin (`caddy-ratelimit`), so the Caddy image is
  built with `xcaddy` in CI, with Caddy and the plugin pinned, like the app's
  images. Each limit is an optional `EDGE_*` setting in `.env`.
* **Spaces.** One private bucket, created ahead of time, and a key scoped to
  it. `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` both name the Spaces
  regional endpoint. The `create_bucket` fallback in `kernel/storage` stays for
  local MinIO only. A lifecycle rule expires exports.
* **Backups.** `make backup-db` runs `pg_dump` from the pinned Postgres image
  and puts the dump in a second, backup-only bucket. A host cron on the
  droplet runs it nightly, and `make restore-db` (destructive, a dependency of
  nothing) is tested once against a scratch database.
* **Swap.** A 1 GB swapfile on the droplet, for the host only. Containers
  keep `memswap_limit` equal to `mem_limit`, so an overrun is still killed
  visibly.
* **The operator's machine is now inside the trust boundary.** The worker
  holds `MASTER_ENCRYPTION_KEY` and connector tokens there. The machine needs
  disk encryption, an `.env` that only its owner can read, and no other
  users. The crawler fetches from the operator's home address, and the
  politeness rules (per-host caps, backing off after a 429 or 403) are
  unchanged.
* **Later, with a domain.** Put Cloudflare's free proxy in front. It hides
  the droplet's address and absorbs floods the droplet would fall over to
  before Caddy could refuse them, which nothing on the droplet can do.

## Limit what one account can do
**Done** (ADR 0054, migration 0045). Where the build differs from the plan
below:

* The counter is incremented in a short transaction of its own, not in the
  request's. A request that fails after it is counted still counts;
  otherwise a flood of bad requests would never be limited.
* The subject is stored only as a digest, so the table keeps no address.
* `FORWARDED_ALLOW_IPS` is optional, defaulting to `127.0.0.1` (believe no
  one), and `docs/deploy.md` lists it among the droplet's settings. A
  required setting would have broken development, where no proxy runs.
* The SPA needed no new screen. The app's refusals carry the wait in their
  message, and the client now writes a message for the proxy's own 429 and
  413, which have no body, and for an error page that is not JSON.

ADR: quotas live in the app, counted in Postgres, because only the app knows
the account.
* **The real client address.** uvicorn runs with `--proxy-headers` and
  trusts `X-Forwarded-For` from Caddy's address only
  (`FORWARDED_ALLOW_IPS`, required on the edge). Otherwise every request
  looks as if it came from Caddy, and a client could also forge the header.
* **A limiter in `kernel`.** A fixed-window counter in a table of its own,
  keyed on what is limited and on whom (an account or an address), and
  incremented in the request's own transaction. A refusal raises the existing
  `RateLimitedError`, which answers 429 with `Retry-After` in the usual error
  envelope. It needs no new datastore, because Postgres is already on the
  droplet.
* **What is limited.** Each limit is an optional setting:
  * accounts created per address per day: there is no address verification
    yet (`architecture.md` open question 3), so a script could otherwise sign
    up thousands of accounts;
  * uploads per account per day: résumés, roles of the user's own and
    template files, each parsed on the operator's machine;
  * connector syncs per account per hour.

  AI work needs no new limit. Each job already runs one of a kind per Target
  at a time, spends the user's own key, and stops at their budget.
* **The SPA** shows a 429's message and when to try again, rather than a
  generic error.
* **Unit tests** for the window rule. Integration tests show each limit
  refusing the request after the allowed count, and the count starting again
  in the next window.

## Release one image to both places
**Done** (ADR 0055). Where the build differs from the plan below:

* The compute machine may be an arm64 Mac, and the droplet is amd64, so a
  release is multi-platform. The release job builds the prod images for both
  platforms with buildx (arm64 under QEMU) and pushes them; their manifest
  digests go in `release.env`. Only the amd64 image is what the gates ran
  against; the arm64 one is the same Dockerfile and commit.
* `make pull-app RELEASE=release.env` takes the file CI writes, not a single
  digest: there are three images.
* CI's push trigger named `main` and `develop`, which this repository does
  not have, so CI never ran on a push to `master`. It now does, and only
  such a push is released.

* **CI** runs `make build-app`, `lint`, `typecheck`, both test tiers and
  `scan`, then pushes the prod images and the Caddy image to GHCR by digest.
  Neither the droplet nor the operator's machine builds anything: a single
  vCPU would take a very long time to install torch and build the SPA, and
  could run out of memory doing it.
* **`make pull-app`** pulls a given digest and tags it `jsa-*:prod`. Compose
  keeps `pull_policy: never`, so `start-app` still runs only what was pulled
  and checked.
* **The release order** is the edge first, which migrates, then the compute
  side. Both run the same digest. A compute site on an older image fails its
  start instead of running against a newer schema (see "Run the app in two
  places").
* **Accepted for now.** The api image carries torch, which it never loads:
  about 2 GB of disk and download on the droplet. A slimmer edge image would
  be a second artifact, and the phase keeps one.

