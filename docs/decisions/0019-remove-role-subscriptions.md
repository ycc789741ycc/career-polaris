# 0019. Remove role subscriptions, and drive board discovery from named companies

**Status:** Accepted — 2026-09-29. Amended by [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md).

## Context

Domain decision 19 let a user watch a role at a company, with an optional
careers or JD link. A watch did four things:
- it widened the user's posting scope to that company's postings;
- it seeded board discovery for the company, and a weekly re-check;
- it allowed a rate-limited manual re-crawl of that company;
- it was a kind of Target, `subscription`, that the Advisor could aim at.

The v3 design (domain decision 22) has no Subscribe button, no watchlist and no
"Roles to watch". The Advisor is aimed from one place, the role map's "Advisor
target" bar (domain decision 26). A watched role was a second way to aim it,
and with one control it had nothing left to do. A match digest with no
watchlist would only repeat the role map.

Board discovery is still wanted: a custom role that names a company should find
that company's board (domain decision 25).

## Decision

Role subscriptions are removed, and board discovery is kept without them.

- **Gone from `market`:** `CompanySubscription`, `SubscriptionAdded`,
  `ManualRefresh`, `Coverage`, the `/role-subscriptions` routes, the
  `refresh_company` and `materialize_crawl_sources` jobs, and the
  `CRAWL_MANUAL_REFRESH_PER_DAY` setting. A user's posting scope is their
  target locations, or the baseline when they have none.
- **The fan-out** resolves a market change to the users whose target locations
  take it in. A company's board changing no longer reaches anyone through it
  on its own.
- **Board discovery stays.** `market.discover_board(company_id, company_name)`
  takes no owner and no link. It probes for a supported board and records one
  as an ownerless `demand` source. A company that already has a source is left
  alone. Nothing queues it until custom roles do.
- **The `subscription` Target kind goes**, with `MatchedPostingView.subscription_id`
  and the SPA's watch form, Subscribe toggle and "subscribed" chip.
- **Migration 0013** deletes plans and résumés aimed at a subscription (their
  milestones, tasks, versions and exports go by cascade) and logs how many. It
  then drops `subscription_id` from `gapplan.plan` and `resume.resume`, rewrites
  their Target checks, and drops `market_user.company_subscription` (with its
  `fanout_read` policy) and `market_user.manual_refresh_log`. The baseline and
  0004 migrations now tolerate the table's absence, so a fresh database still
  migrates.

## Consequences

Easier:
- One way to aim the Advisor. A Target is an opening or a pasted JD until
  ADR 0022 makes it a role.
- Less cross-user reading: the fan-out touches one table, not two.
- A latent bug goes with the code: the queued discovery task took no `url`,
  though the route sent one.

Harder:
- Nothing tells a user when a company they care about opens a role. They find
  out by opening the role map.
- A user's scope no longer includes a company's postings outside their target
  locations. A custom role that names the company is the way back in.
- Plans and résumés aimed at a watched role are deleted, not kept. They
  pointed at a row that no longer exists, and the Target model has no kind for
  them. Downgrading restores the empty tables and column, not those rows.

## Alternatives considered

- **Keep subscriptions, but stop offering them as Targets.** Lost: a watch
  would still widen the scope and cost crawls, for a list the product no longer
  shows.
- **Turn each subscription into a custom role.** Lost: custom roles arrive in a
  later step, and a watched role at a company has no JD, so it would become a
  role with nothing to score. Users can add one themselves once custom roles
  exist.
- **Keep plans and résumés aimed at a subscription, frozen on their snapshot.**
  Lost: every read path resolves a Target from its kind, and a kind with no
  source would need special cases everywhere for a handful of rows.
