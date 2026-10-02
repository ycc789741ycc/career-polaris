# 0032. Work out every opening's fit locally from its role's, and rank a role's openings by it

**Status:** Accepted — 2026-10-04. Amends [0022](0022-make-a-target-a-role-and-an-optional-opening.md) and [0028](0028-score-the-fit-in-the-role-map.md).

## Context

Until now an opening had no fit of its own. Every row of "Top matched
openings" carried its role's `RoleFit` score (`fit_basis: "role"`), so all of
a role's openings scored the same. The list was drawn across every role,
ranked by role fit, one per company, and picking a bubble did not change it.
ADR 0022 made a Target with an opening use the role's fit.

Two openings in one role can ask for quite different things: one stresses
what the user is strong in, another their gap. Showing that, for the role
being looked at, needs a fit per opening. There were two ways to get one:

- **Score each opening as a role is scored.** One AI call per opening instead
  of one per role: on the user's ledger, a fit call averages about $0.08, so
  ten roles of ten openings would be about $7.80 a build instead of $0.78.
- **Use similarity alone,** as the free fit estimate (ADR 0027) does. It says
  a topic is present, not the level expected, so there are no targets and no
  gaps. Something the user lacks has nothing to be similar to, so there are
  no uncovered requirements, and no closing lifts to rank a plan's gaps by.
  On the dev data, the estimate's rank agreement with the AI fits ranged from
  0.48 down to −0.48.

## Decision

The AI evaluates each role's requirements once, as now; each opening's fit is
worked out from that locally, and is never an AI call.

- **The rule** (`rolemap/domain/fit.py`, pure, no I/O):
  - `get_requirement_relevance` compares each requirement statement's
    embedding with each opening's, and centres the similarity on that
    requirement's mean over the role's openings. One every opening asks for
    alike is 0 everywhere; one an opening stresses is above 0 there.
  - `get_opening_fit` scales each requirement's weight by
    `1 + OPENING_EMPHASIS × relevance`, at most `OPENING_WEIGHT_CEILING`. Under
    `OPENING_WEIGHT_FLOOR` the opening does not ask for it, and it drops out.
    A dimension counts by the weight its requirements kept, relative to the
    role's (`SkillGap.weight`). `evaluate` and `closing_lifts` take that
    weight, so the score and the lifts agree. With every opening alike, each
    scores its role's fit.
  - The three numbers are in `rolemap/domain/constants.py`.
- **Where it runs.** `compute_fits`, after scoring the roles, works out every
  opening's fit (`_derive_opening_fits`) in the worker. It embeds each role's
  requirement statements, reads the openings' stored embeddings, and never
  touches the gateway. A role whose `RoleFit` was reused still has its
  openings worked out.
- **What is stored.** A `PostingFit` with `basis = role`, keyed on the
  opening's `posting_key`, naming its `role_id` (`ON DELETE CASCADE`) and the
  `RoleFit` it came from (`source_fit_id`). A check constraint ties `role_id`
  to that basis.
  - It is a cache of a pure computation: each build replaces a role's
    openings' fits as a set, and the table could be emptied and rebuilt from
    the fits and the embeddings with no AI call.
  - It is stored because Top matched is a list: it sorts and pages by score,
    and its inputs change only when a build runs. An opening that left the
    market since drops out when the list is read, against the live scope.
- **Top matched follows the selected role.** `GET /matched-postings?role_id=`
  ranks a role's openings by their own fit (`fit_basis: "posting"`), or by
  the role's for one not worked out yet (`"role"`). `one_per_company=true`
  keeps each company's best; the SPA asks for it, with `page_size=10`, for the
  selected bubble and reloads on every pick. The bubble's count and the
  Advisor's opening picker ask without it and see every opening.
- **A Target with an opening plans against the opening's fit.**
  `target.snapshot` reads `rolemap.opening_fit` and freezes it, with a new
  `RequirementBasis.OPENING`. Before a build has worked it out, the role's fit
  stands in, with basis `role`. Resolving either still spends nothing.
- **Migration 0028** adds `role_id` and the constraints. It writes nothing:
  the next build works the fits out.

## Consequences

- **Easier.**
  - Openings in one role rank by how well the user fits each, at no cost.
  - A plan or résumé aimed at an opening is planned against what that opening
    stresses, with lifts to match.
  - The cost of a build grows with its roles, not its openings.
- **Harder.**
  - An opening's fit can only see what its role's requirements name. A
    requirement only that opening asks for is invisible to it; the exact fit
    would need an AI call over its description.
  - One embedding per opening blurs a long description, so the reweighting is
    coarse. It ranks openings within a role; it is not a verdict on one.
  - The three constants are judgement, set by hand, with nothing yet to tune
    them against.
  - The worker embeds every requirement statement on each build: local CPU on
    the `ai` queue.
  - The Advisor's plan for an opening can differ from its plan for the role.
  - The list across every role is gone from the SPA, though the API still
    answers it.

## Alternatives considered

- **An AI fit per opening.** Exact, and ten times the cost of a build, for a
  ranking the user glances at.
- **Similarity alone.** Free, but no targets, gaps or lifts, and on real data
  it ranked roles about as well as chance.
- **Compute opening fits on every request, storing nothing.** No cache to
  keep, but the api runs no embedding model, the list could not page in SQL,
  and pages could reorder between requests.
- **An AI fit only for the opening the user aims at.** Kept as an open
  question: worth it once a user can ask for the exact fit of one opening,
  priced and confirmed like a posting of their own.
