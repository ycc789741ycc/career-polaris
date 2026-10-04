# 0049. The role map lists a role's openings newest first, without a fit

**Status:** Accepted — 2026-10-04.

## Context

Since ADR 0032 every opening has a fit of its own, worked out locally from
its role's: the role's requirements reweighted by how much the opening asks
for each. The role map's "Top matched openings" ranked the selected role's
openings by it, one per company, ten at most, each with its percentage, and
picking a row aimed the Advisor at that opening.

The 4 October prototype reads the fit as the role's. A user sees one score on
the role, then ten slightly different scores beneath it that the AI never
gave, and reads them as ten assessments. What they want from the list is the
openings themselves: who is hiring for this role now, and what is new.

## Decision

The role map lists "Openings for this role": every open posting in the
selected role, newest first, with no fit.

- **Newest first.** `GET /matched-postings` takes `order`, `fit` (the default,
  as before) or `newest`. `rank_matches` sorts by `posted_on` descending,
  undated last, then by role, company and title, so the order is stable.
- **A posting's day.** `MatchedPosting.posted_on` is the day its source says
  it was posted, else the day it was first fetched. The row shows it as "2
  days ago".
- **Every opening, ten at a time.** The list asks for
  `one_per_company=false&order=newest&page_size=10`, says how many there are,
  and "See all n openings" pages through the rest with Previous and Next.
- **No fit, and nothing to pick.** A row shows the company, the posting
  (linked), its place, its pay and its credit. It is not a button, so the
  sticky "Advisor target" bar aims at the role only.
- **Opening fits stay.** `compute_fits` still works out each opening's fit, and
  a Target that names an opening, set before this, still plans against it
  (`RequirementBasis.OPENING`). Nothing is migrated.

## Consequences

Easier:

- The one fit a user sees is the role's, the score the AI gave.
- The list answers what a user looks for here — who is hiring, and since
  when — and shows all of them, not the best ten.

Harder:

- A new Target can no longer name one opening from the map. Opening fits are
  computed on every build for Targets that already name one, and for nothing
  else a user can reach, until they are either surfaced again or removed.
- `posted_on` falls back to the first fetch, so a posting found late reads
  newer than it is.
- The list pages on the server over a ranking built in memory, as before:
  every page reads the role's postings again.

## Alternatives considered

- **Keep each opening's fit, and sort by date.** Lost: the prototype's point
  is that the percentages read as separate assessments, whatever the order.
- **Remove opening fits and opening Targets altogether.** Lost for now: it
  touches stored plans, résumés and question sets that name an opening, and
  the user chose to keep them.
- **Load every opening and page in the browser.** Lost: a broad role has
  hundreds, and the API already pages every list (ADR 0014).
