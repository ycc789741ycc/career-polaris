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
