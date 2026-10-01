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
## Build the role map once, after the market search
Today an analysis builds the role map twice. `AnalysisFinished` builds it at
once from the postings already crawled (ADR 0020). Then the Himalayas
searches for the analysis's candidate roles (ADR 0025) land a few minutes
later, `PostingsChanged` rebuilds it, and most roles are named again because
their openings changed. That roughly doubles the naming and fit calls on the
user's key for every analysis, and the map reshuffles under them.

The defined process is: the analysis recommends roles from the user's
strengths, the market is searched for those roles, and the ten that fit best
among what the market has become the map. So the immediate build goes, and
the one build waits for the search.

One branch, `feature/<ticket>/build-after-search`, cut from mainline once
`feature/no-ticket/himalayas-candidate-search` has merged, with the same
definition of done as Phase 5: tests in the right tier, every gate passing
with nothing skipped, its ADR (0026 at the time of writing, amending 0020
and 0025) and the index, and `CLAUDE.md` and `README.md` saying what is built.

1. **The build after an analysis waits for the search.**
   * `activity.build_after_analysis` records the build as `waiting`, not
     `running`, and queues nothing. The cost is still the one the user
     confirmed with Analyse.
   * A waiting build now waits for either an analysis or a market search.
     `BuildRun` says which, so the running bar can say "Searching the market
     for your recommended roles" rather than "waiting for the analysis".
   * A failed analysis still only releases a build that waited for it, and
     records no new one.

2. **Searches are requested where the answer is known.**
   * On `RoleCandidatesReplaced`, the dispatcher calls
     `market.request_searches` itself instead of queueing
     `market.request_searches`. It is a few writes, and the dispatcher needs
     the answer: how many searches are new.
   * None new means nothing to wait for: the user chose only regions, which
     add no search ("Choose target locations from a list" below), or every
     title's search is already crawled (a re-analysis). The dispatcher starts the waiting build at once, through
     `activity.request_role_map`.
   * The crawl sources stay ownerless. Only titles and places reach `market`;
     the user id never leaves the dispatcher.
   * `RoleCandidatesReplaced` is recorded before `AnalysisFinished`, so the
     build may not exist yet when the searches are requested. The rule has to
     hold in either order: whichever of the two events comes second starts the
     build when there is nothing to wait for.

3. **A search that finishes always says so.**
   * `crawl_new` announces every place it searched, even when nothing changed,
     because a waiting build is waiting for it. `request_role_map` already
     starts a waiting build when asked again with nothing running.
   * The weekly crawl keeps announcing a place only when an opening appeared
     or went, so a quiet market still rebuilds nobody.

4. **A deadline, so a slow or failing search never holds the map back.**
   * A build still waiting `SEARCH_WAIT_SECONDS` (5 minutes to start with)
     after it was recorded starts anyway, on the postings there are. A 429 or
     a stopped crawler costs the user the searched postings, not the map.
   * The check runs in the worker's dispatch loop, beside the outbox polling,
     and reads only open builds. It reuses ADR 0018's staleness clock rather
     than adding a scheduler.
   * A build waiting on an analysis keeps today's rule: it starts when the
     analysis ends, or is closed as lost with it.

5. **What stays as it is.**
   * Every other trigger builds as now: "Rebuild role map", adding a custom
     role, a change of target locations, and the weekly crawl's
     `PostingsChanged`.
   * A change of target locations also requests searches for the new places.
     Whether that build should wait for them too is open; the first cut keeps
     it immediate.
   * Fits are still scored once per finished build.

Tests:
* Unit: `activity` records a waiting build after a successful analysis and
  starts it on request; the dispatcher starts the build at once when no
  search is new, in both event orders, and leaves it waiting otherwise;
  `crawl_new` announces unchanged places and the weekly crawl does not; the
  deadline starts a build waiting on the search and leaves one waiting on an
  analysis alone.
* Integration: one analysis leads to one build and one `compute_fits`, with
  the searched postings in scope; a re-analysis with the same titles builds
  without waiting.
* SPA: the running bar's "searching the market" state.

What gets harder:
* The map arrives later: up to two minutes for the crawler's look, plus the
  crawl and the build, so three to five minutes after the analysis instead
  of straight after it. The running bar has to make that wait legible.
* Every analysis now depends on the crawler being up and Himalayas
  answering, bounded by the deadline.
* A waiting build has two meanings, so ADR 0018's rule and the activity
  copy widen.

Open questions:
* `SEARCH_WAIT_SECONDS`: 5 minutes is a guess. The crawler's poll is two
  minutes, and twenty searches at the per-host rate limit take most of a
  minute; measure it before settling.
* Whether a change of target locations should also wait for its searches
  (step 5).

## Expire searched postings by age, not by absence
How an opening closes today depends on its source:

* **A company board** (Greenhouse, Lever, Ashby, a JSON-LD career page)
  lists every opening the company has. One missing from a successful crawl
  is closed, and `expire_unseen` marks it expired at once.
* **A Himalayas search** returns only its first page, about twenty jobs,
  because robots.txt forbids paging (ADR 0025). The same rule reads "pushed
  off page 1 by a newer job" as "closed". A busy title then reports a change
  on nearly every crawl, which rebuilds role maps for nothing, and an opening
  that is still real drops off the map.

What stays the same for every source:

* A failed fetch expires nothing.
* An expired posting is kept, not deleted. It leaves the role map, the
  openings and the market scope, and still counts toward salary-band history.
* Seen again, it reopens.
* A retired search (eight weeks unasked) expires everything it found.

The same opening returned by two searches makes it worse. It belongs to
whichever source saw it last (`seen_again`), and only that source can expire
it. If it then leaves that search's first page, it expires, though the other
search still lists it, until the other's next crawl reopens it.

Its own branch, `feature/<ticket>/search-posting-expiry`, cut from mainline.
It lands before "Build the role map once, after the market search", whose
waiting builds rely on a search announcing a change only when the market
really moved. ADR 0025 is amended in the same branch.

1. **A searched posting expires when nobody has seen it for a while.**
   * A posting whose source is a search is expired when its `last_seen_at` is
     older than the unseen age, not when one crawl misses it. `last_seen_at` is per posting,
     so any search, or a company board, that still returns it keeps it open,
     whichever source it belongs to.
   * The age is `SEARCH_POSTING_UNSEEN_DAYS` in `.env`, optional with a
     default of 7, declared in `.env.example` beside the other `CRAWL_*`
     settings. `kernel.config` reads it once at start-up and rejects anything
     under 1. The crawler's wiring passes it to `market` as a `timedelta`, so
     the domain holds no number of its own.
   * `record_search_crawl` stops calling `expire_unseen`. Its `changed` is
     then just "an opening appeared or reopened".
2. **One sweep per crawl run.**
   * After a crawl run's searches (`crawl_new` and the weekly crawl), one
     query expires every open searched posting past the age, using the
     existing `(status, last_seen_at)` index.
   * The sweep returns the places those postings were found for, and the run
     announces them with the places that changed, still once per place.
3. **Boards keep expiry by absence.** Their list is complete, so a missing
   opening is a closed one, and that is noticed the next crawl rather than
   `SEARCH_POSTING_UNSEEN_DAYS` later.

Tests:
* Unit: a searched posting missing from one crawl stays open; one unseen for
  the configured age is expired by the sweep and its place announced, and
  one just short of it is not; the setting defaults to 7 and rejects 0; a posting another search still returns stays open; a board
  posting missing from a crawl still expires at once; a search crawl that
  finds only known openings reports no change.
* Integration: the sweep's query against real rows, scoped to searched
  postings only.

What gets harder:
* A job closed on Himalayas stays on the role map for up to
  `SEARCH_POSTING_UNSEEN_DAYS`, a week by default. Its
  link then goes to a closed listing, and the fit counts an opening that is
  gone.
* Expiry now has two rules, by source kind, and the sweep is one more step
  in each crawl run.
* Openings counted per role and per place run a little high for searched
  postings, by the ones closed within the unseen age.

Open questions:
* Whether Himalayas' payload carries an expiry date per job. If it does, a
  job past it could close on that date, and the age rule would only catch
  the ones that vanish early.
* Whether 7 days is enough. A search is crawled once when it is new and then
  weekly, so a posting seen at one weekly crawl and missed at the next is
  about 7 days unseen at that crawl's sweep: with the default, a single
  weekly miss can still expire it. Count how often a job leaves page 1 and
  comes back, and raise the setting (14 is two weekly crawls) if the weekly
  crawl keeps flipping postings.

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
It lands before "Build the role map once, after the market search", which
relies on every place being either searched or plainly not. Same definition
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
     ("Taipei", "Hsinchu", "Kaohsiung" for Taiwan). `in_market`,
     `get_open_in_scope`'s SQL and `scope_names` (the fan-out) read them, so
     a board posting in Taipei is in scope for "Taiwan" and its change
     reaches the Taiwan users.
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
   * It still sees searched postings: those of a member country that some
     user chose, and remote work open worldwide, searched for whoever chose
     "Remote".
   * The fan-out resolves a changed place to its regions as well: a change
     announced for "Germany" also reaches users who chose "Europe".

5. **The screen.**
   * `TargetLocations.tsx` swaps the text input for a searchable select:
     type to filter, pick to add. Options are grouped Remote, Regions,
     Countries, and places already chosen are shown but can't be picked.
   * Chips, the "n of 3 chosen" count and removing a location stay as they
     are. Each change still saves the whole set and emits
     `TargetLocationsChanged`.
   * A chosen region's chip is marked, with one line under the list: "Regions
     use the postings we already have. Pick a country for a fresh search of
     your recommended roles." The copy no longer says "City, country or
     Remote region".

6. **Stored locations are moved over.**
   * A migration rewrites each `market_user.market_preference` row to its
     option: "UK" → "United Kingdom", "Remote Taiwan" → "Taiwan", "EU" or
     "Remote EU" → "Europe", dropping duplicates.
   * A row that maps to no option (a city, an unknown region) is deleted, so
     the user sees one fewer location, or none. Users who had a role map get
     one `TargetLocationsChanged`, so the map rebuilds on the new scope.

Tests:
* Unit: options are "Remote", the regions, then the countries, each group A
  to Z, one per country; every country is in a region;
  `chosen_target_locations` rejects an unlisted place; a country takes in a
  posting that names only one of its cities; a region takes in a posting in
  any member country and remote work open worldwide, and nothing else;
  a region requests no search; a change announced for a country reaches
  users of its regions; the migration's mapping, including a dropped city.
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
* Fan-out widens: one country's change now reaches its regions' users too,
  and "Europe" users rebuild when any member country moves.
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
