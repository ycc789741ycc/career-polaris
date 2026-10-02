# 0021. Let users add roles of their own beside the ten, and make a pasted JD belong to one

**Status:** Superseded by [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md) — 2026-09-29.

## Context

The role map analyses the ten recommended roles closest to the user's profile
(ADR 0020). That misses the role a user already has in mind: a step up, a
change of field, or one company they want. Until now the only way to aim at
such a role was to paste its JD, which became a Target of its own but never
appeared on the map. Pasted JDs were also clustered with the crawled postings,
so one could quietly become part of a recommended role.

The v3 design (domain decision 25) asks "Not seeing a role you want?" and takes
a job title (required), a company (optional) and a JD (optional, private). The
role is analysed against the user's strengths and placed on the map beside the
ten, drawn green and labelled "yours".

## Decision

- **A custom role is a `rolemap.role` with `origin = 'custom'`**, plus an
  optional `company_name` and an optional `private_posting_id` for its JD in
  `market_user.private_job_posting`. Migration 0015 adds the columns.
- **Reconciliation never touches it.** Only recommended roles' members are
  "previous" to `reconcile`, so a custom role is never retired by a rebuild and
  does not count toward the ten. The user removes it with
  `DELETE /roles/custom/{id}`, which retires it, so plans and résumés aimed at
  it keep their snapshots.
- **Each build places every custom role.** Postings in the user's scope match
  it when every word of its title is in theirs, and every word of its company
  is in theirs when one was named. This uses the same accent-folded word rule
  as target locations, now `market.names_every_word`. The matches are its
  openings and give it a salary band. Its requirements and hiring bar are read
  from its JD when there is one, else from the matches, with the same two calls
  as a recommended role. With neither, it stays on the map unscored. A custom
  role whose matches have not changed costs nothing on the next build, and the
  analysis never renames it.
- **Adding one.** `POST /roles/custom/cost-estimate` prices it first.
  `POST /roles/custom` stores the JD through `MarketService.paste_job_description`,
  creates the role, records `CustomRoleAdded`, and records the build that
  places it, as the rebuild route does. The dispatcher sends a named company to
  `market.discover_board`, which may leave an ownerless `demand` crawl source.
  `POST /job-descriptions` is gone: a JD now arrives with a custom role.
- **Pasted JDs leave clustering.** `postings_in_scope` is the shared postings
  in the user's target locations (or the baseline), and nothing private.
  Migration 0015 turns every JD already pasted into a custom role, titled from
  the JD, at its company, and logs how many.
- The SPA's "Add a role of your own" form replaces `OwnJd.tsx`, and
  `charts/RoleMap.tsx` draws custom roles in the second series colour,
  labelled "yours". Until Targets become roles (ADR 0022), a custom role with a
  JD aims the Advisor through that JD.

## Consequences

Easier:
- The role map shows what the user is aiming at, not only what the market
  suggests, and a pasted JD is always on it.
- The spend goes where the user points it: one role, priced before it is added.
- A company named on a custom role gets its board crawled, for everyone,
  without anyone's name on it.

Harder:
- Every build now places custom roles too. An unchanged one is free, but a
  crawl that brings it new matches re-reads it on the user's key.
- Title matching is literal. "Staff Backend" does not take in "Senior Software
  Engineer, Server" even when that is the same job. The JD is the way to
  sharpen it.
- A custom role with no salary in its matches has no Y position. It is listed
  under the chart, not plotted.
- Existing pasted JDs become roles nobody explicitly added. They are titled
  from the JD and can be removed.

## Alternatives considered

- **Cluster the custom role's matches with the rest and adopt the nearest
  cluster.** Lost: the user named a role, and the nearest cluster is often a
  different one. Matching by title is predictable and needs no model.
- **Keep pasted JDs as a Target of their own beside custom roles.** Lost: two
  ways to aim at "my own role", one of them invisible on the map. The design
  keeps exactly one.
- **Delete a removed custom role outright.** Lost: fits, plans and résumés
  point at role ids, and every other role that leaves the map is retired.
