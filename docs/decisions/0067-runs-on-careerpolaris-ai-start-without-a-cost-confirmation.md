# 0067. Runs on CareerPolaris AI start without a cost confirmation

**Status:** Accepted — 2026-10-11. Amends domain model 2.10.

## Context

Every AI action a user starts first shows "Before we spend anything": an
estimate in dollars, and nothing runs until they choose "Run it" (domain model
2.10). The rule exists because the money is the user's: their own key, their
provider's bill, their monthly cap.

On CareerPolaris AI (ADR 0064, ADR 0066) the money is the operator's. What
binds the user is the free monthly quota, which they see as a percentage. A
dollar confirmation there asks them to approve a spend that isn't theirs, in a
unit they're never shown elsewhere. It also puts a stop in front of every
step of the journey on the very path meant to need no setup.

## Decision

- **On CareerPolaris AI, a run starts as soon as it is asked for.**
  `CostConfirm` shows nothing and calls its `onConfirm` once, when it mounts.
  A ref guards the call, so React's double mount in development can't start
  the run twice. Each flow still asks for its estimate first, as before.
- **On the user's own key, nothing changes.** The estimate and "Run it" stay,
  and the confirmation names who pays ("Runs on your own key on …").
- **The quota is the limit.** A run that the quota or the ceilings can't take
  is refused when it starts (`ai_platform_quota_reached`,
  `ai_platform_unavailable`, `ai_platform_call_too_large`), and that refusal
  links to AI settings, as before.

## Consequences

Easier:

- The platform path really has nothing to set up or approve. Analyze,
  rebuild, target, plan, résumé and questions each start with one click.
- One change in `CostConfirm` covers every flow, and any added later.

Harder:

- **A user on the platform can't see what a run costs before it runs.** They
  see its effect on the quota percentage afterwards.
- **A user can use up the month's quota in a few clicks.** The per-account
  quota, the per-call maximum and the ceilings bound it.
- **A run that won't fit is refused at its start,** after the click, rather
  than at a confirmation.

## Alternatives considered

- **Keep the confirmation and show the quota line in it.** That was the
  behaviour before; the user rejected it.
- **Show a percentage of the quota instead of dollars, and keep "Run it".**
  It is still a stop on the path meant to have none. And an estimate's share
  of the quota is a ceiling guess, so it would usually overstate the run's
  cost.
- **Skip fetching the estimate on the platform.** That would mean changing
  each of the seven flows. Fetching it costs nothing, and keeps one path
  through each flow.
