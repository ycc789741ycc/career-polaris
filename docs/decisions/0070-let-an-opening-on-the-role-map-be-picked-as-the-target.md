# 0070. An opening on the role map can be picked as the Advisor's target

**Status:** Accepted — 2026-10-11. Supersedes 0049.

## Context

ADR 0049 made the role map's "Openings for this role" a plain list: every
open posting in the selected role, newest first, with no fit, and nothing to
pick. The sticky "Advisor target" bar aimed at the role only.

That left a Target naming one opening (ADR 0022) reachable only from one set
before 0049, while `compute_fits` still worked out every opening's fit (ADR
0032) on each build. Users want to aim the Advisor at a posting they found on
the map: its questions, plan and résumé measured against what that opening
asks for, not the role in general.

## Decision

An opening in "Openings for this role" can be picked, and the Advisor is then
aimed at it.

- **Pick, per row.** Each row keeps its company, linked posting, place, pay,
  credit and age, and gains a Pick button (`aria-pressed`). Picking sets the
  hash's `opening` beside the role; the row is highlighted and its button reads
  "Picked ✓". Pressing it again, or picking another role on the map, goes back
  to the role.
- **One Target at a time.** The bar names "<role> · <company>" and reads
  "Target this opening", or the role and "Target this role" when nothing is
  picked. Either prices and starts the questions as before; the Target is
  `(role_id, job_posting_id)` and is remembered as ADR 0050 says.
- **An opening picked on another page stays picked** while its role is
  selected; one the hash names that is no longer in the role is ignored, and
  the bar aims at the role.
- **Still no fit per row.** The map's one fit is the role's, for 0049's
  reason. The Advisor shows the opening's own fit once aimed at it, as it
  always has for an opening Target.
- **What stands from 0049.** The list is newest first by `posted_on` (the
  source's day, else the first fetch), ten at a time with "See all n
  openings", from `GET /matched-postings?order=newest&one_per_company=false`.
  Nothing on the server changes.

## Consequences

Easier:

- A plan, questions and a résumé can aim at one real posting again, from where
  the user finds it, and the opening fits every build computes are used.
- No backend, schema or migration change: the Advisor already resolved an
  opening Target.

Harder:

- The Advisor's "Fit today" for an opening can differ from the role's fit the
  map just showed, with nothing on the map explaining why.
- A picked opening can leave its role at the next build; the Advisor then
  says the target left the map, and the user picks again.
- Each row carries a second control beside the posting's link, so the list is
  busier than 0049's.

## Alternatives considered

- **Show each opening's fit again, and pick by row.** Lost: ten percentages
  beneath the role's read as separate assessments, which is why 0049 removed
  them.
- **Make the whole row the button.** Lost: the posting's own link would sit
  inside a button, which is neither valid markup nor clear to a screen reader.
- **Aim at an opening only from the Advisor.** Lost: the user finds the
  opening on the map, and a second screen to pick it there is a detour.
