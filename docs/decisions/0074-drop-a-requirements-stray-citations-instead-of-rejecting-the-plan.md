# 0074. A requirement's stray citations are dropped, not the gap plan

**Status:** Accepted — 2026-10-11.

## Context

ADR 0036 let an uncovered requirement in a gap plan cite the answers the user
gave about it in Fill the gap, and nothing else, and checked that in code:
`assert_draft_valid` rejected the whole draft as `plan_invalid` when a `req:`
gap cited anything outside its own answers.

A real plan drafted on CareerPolaris AI failed that way:

> the drafted plan was rejected: gap
> req:communicate-complex-technical-concepts-and-ai-agentic-workflows-clearly-to-both-
> has no evidence but its own answers to cite, and cites ['E16', 'E17',
> 'E19', 'E2', 'E22', 'E7']

The prompt (`gap_plan` v3) states the rule. The model broke it anyway, for a
soft-skill requirement that ordinary facts seem to bear on. The rest of the
plan — every other explanation, the milestones, the tasks — was sound, and it
was thrown away after it had been paid for. A regenerate can fail the same
way, because the same requirement invites the same citations.

As in ADR 0046, the rule guards two different things:

- **That every citation is the user's own.** `assert_citations_exist` checks
  every citation against the profile, and an invented one still rejects the
  draft (`evidence_not_owned`).
- **What an uncovered requirement may rest on.** That is a rule about which
  of the user's own facts a requirement shows, not a fabrication.

## Decision

A requirement's stray citations are dropped; the plan stays.

- `get_readings_settled(readings, dimension_keys=, answers_by_gap=)`, pure,
  in `gapplan/domain/plan.py`, keeps each `req:` gap's citations that are its
  own answers and drops the rest. Its `why` is kept as written. A `dim:` gap
  keeps everything it cites.
- `GapPlanService._draft` settles the readings before `assert_draft_valid`
  and logs how many citations it dropped (`gapplan.citations_dropped`).
- `assert_draft_valid` no longer takes `answers_by_gap`, and no longer rejects
  a `req:` gap's citations. Its other rules stand.
- The prompt is unchanged: `gap_plan` v3 still tells the model a `req:` gap
  cites only its own answers.

This amends ADR 0036's "The rule is checked"; the rest of ADR 0036 stands.

## Consequences

Easier:

- A model that over-cites one requirement no longer costs the user the plan,
  and a regenerate does not fail on the same requirement.
- What the plan shows under a requirement is still only the user's answers
  to it, enforced in code.

Harder:

- A requirement's `why` may still describe the facts it cited ("your write-ups
  show…"), though the plan no longer lists them under it. The words name only
  the user's own work, but nothing on the page backs them.
- The model's mistake is silent to the user; it shows only in the log count.

## Alternatives considered

- **Keep rejecting, and let the user regenerate.** Lost: the same requirement
  fails the same way, and each attempt is a spend.
- **Drop the requirement's explanation, or the requirement.** Lost: every
  shown gap must be explained, and a plan with the gap missing would plan
  less than the user asked for.
- **Ask the model again within the same call.** Lost: as in ADR 0046, the
  gateway re-asks only on a schema failure, and a second round for a citation
  doubles the cost of the cases where it happens.
