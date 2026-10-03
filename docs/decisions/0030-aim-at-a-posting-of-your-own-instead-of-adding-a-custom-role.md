# 0030. Aim the Advisor at a posting of your own instead of adding a custom role

**Status:** Accepted — 2026-10-04. Supersedes [0021](0021-let-users-add-custom-roles-beside-the-ten.md), and amends [0022](0022-make-a-target-a-role-and-an-optional-opening.md) and [0027](0027-fetch-the-market-only-when-a-build-needs-it.md). Amended by [0033](0033-keep-a-posting-of-your-own-in-target.md) and [0034](0034-add-a-role-of-your-own-without-evaluating-it.md).

## Context

ADR 0021 let a user add a role of their own to the role map: a title, an
optional company and an optional pasted JD. A custom role was a
`rolemap.role` with `origin = 'custom'`.
- Every build matched it to postings by title words and asked for its
  company's board through board discovery.
- Every build named it, read its requirements and scored its fit on the
  user's key, outside the top k (ADR 0029).
- ADR 0022 made a Target a role and an optional opening, so a pasted JD could
  only be aimed at through the custom role it came with.

Living with it showed the fit was wrong:
- **The user wants a posting, not a role.** They bring one job they found,
  to plan for and tailor a résumé to. Turning it into a role spends every
  build matching it to postings like it, which they did not ask for.
- **It was half a role.** A role is a group of openings and what they ask
  for. A custom role carried a company and a JD, which describe one posting,
  and `Role` had three columns only custom roles used.
- **It spent the key on every build.** Naming, requirements, a hiring bar and
  a fit for each custom role, whatever changed.

## Decision

A posting the user brings themselves is aimed at from the Advisor, and never
added to the role map.

- **"Aim at a posting of your own"** in 04 Advisor replaces "Add a role of
  your own" in 03 Roles. It takes a title, an optional company and the JD.
  - The JD is required: nothing else says what the posting asks for.
  - The JD is stored as before, in `market_user.private_job_posting`.
  - The cost is confirmed first. The run that reads and scores it is
    recorded before it is queued (`rolemap.posting_evaluation`, ADR 0006),
    and the Advisor polls it.
- **A Target is a role (and optionally one of its openings), or a posting of
  the user's own.** `TargetRef` takes `role_id` with an optional
  `job_posting_id`, or `private_job_posting_id` alone, and refuses both or
  neither. `gapplan.plan`, `resume.resume` and `gapfill.question_set` gain a
  nullable `private_job_posting_id`, `role_id` becomes nullable, and a check
  constraint keeps exactly one set. The Advisor's hash names one as
  `?posting=`.
- **The AI evaluates the posting's requirements once, and its fit is worked
  out locally.** In `rolemap`, which keeps the one set of fit rules (ADR 0028):
  - `PostingRequirement` holds what the JD asks for, read once (`rolemap.extract`).
  - `PostingRequirementFit` is the AI's evaluation of them (`rolemap.fit`):
    the mapping onto the user's dimensions, the targets and the reasoning.
  - `PostingFit` (`basis = own`) is worked out from it with no AI call:
    `get_posting_fit` evaluates the mapping and targets against the user's
    scores. It carries the score, gaps, uncovered requirements and closing
    lifts the Advisor reads.
  - Adding a posting costs two calls, and nothing else on it calls the AI.
    There is no hiring bar: the fit never reads one.
  - No build reads or scores it. After a new analysis the Advisor says its fit
    was scored against earlier strengths and offers to rescore it, which
    re-runs the projection only. Nothing is rescored unasked.
- **The role map loses custom roles.**
  - `Role` loses `origin`, `company_name` and `private_posting_id`. It is a
    group of openings and what they ask for, and k roles are the whole map.
  - `RoleOrigin`, `CustomRoleError`, `add_custom_role`, `/roles/custom` and
    `CustomRoleAdded` are gone.
  - A build no longer asks for custom roles' companies' boards
    (`market.request_sources` takes titles and places only). Board discovery
    had no other caller, so it goes too: `market.discover_board`, its job and
    the probing in `market/crawling`. Recognising a board URL stays, in
    `crawling/board_urls.py`.
- **Migration 0025** moves each custom role with a pasted JD to a posting of
  the user's own. Its requirements, its latest fit and a finished run are
  copied over, and the plans, résumés and question sets aimed at it are
  pointed at the posting. Every custom role is then retired and its members
  dropped. A custom role without a JD is only retired, and what was aimed at
  it stays as history.

## Consequences

- **Easier.**
  - A build spends nothing on postings the user brought.
  - A role means one thing: a group of openings.
  - A posting of your own is planned against its own JD, not a role built
    around it.
- **Harder.**
  - A Target has two shapes. Every reader of `TargetRef` handles both, and
    three tables carry two nullable columns and a check.
  - A posting of your own is no longer matched to others like it, so nothing
    says how many similar openings the market has.
  - `rolemap` scores something that is not on the map. The fit rules stay in
    one place at the cost of the component's name meaning a little less.
  - A posting's fit goes stale after an analysis until the user rescores it.
  - A company named by a user no longer leads to its board being found.
    Postings beyond the baseline boards come only from the candidates'
    searches.
  - The migration cannot be undone: a downgrade gives `rolemap.role` its
    columns back, every role `recommended`, but does not turn postings back
    into custom roles.

## Alternatives considered

- **Keep custom roles, and score them only when asked.** This fixes the
  spending but keeps a role that is really one posting, with its company and
  JD on `Role`. It also still matches the posting to others on every build.
- **Store the posting's fit as one AI record, as a `RoleFit` is.** Simpler,
  one table fewer. But branch 4 of Phase 8 works out every opening's fit
  locally from its role's. Keeping the AI evaluation (`PostingRequirementFit`)
  apart from the worked-out fit (`PostingFit`) gives both kinds of posting the
  same rule: a `PostingFit` is never an AI call.
- **Put the evaluation in `target`.** `target` has no tables (ADR 0005), and
  the fit rules would be split between two components.
- **Accept a title and company without a JD, searched on the market.** That
  is a custom role again, and the search would name a role rather than the
  posting the user meant.
