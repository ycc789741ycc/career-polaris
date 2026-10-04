# 0050. The Advisor's target is kept in the browser

**Status:** Accepted — 2026-10-04.

## Context

The Advisor works against one Target (ADR 0022, 0030). Until now the Target
was whatever the hash carried. The role map wrote the same hash when a bubble
was picked, so picking a bubble and then the sidebar's Advisor link aimed the
Advisor at that role. Nobody had chosen it.

The 4 October prototype makes setting a target an act:

- No target exists until the user clicks "Target this role" on the role map,
  or "Set as target" on a role of their own.
- Until then, the Advisor shows "No target yet", with its steps locked.
- A banner control, "Previous targets", switches back to a role targeted
  before. Its answers, plan and résumé are restored with no AI call.

The server holds no "current target". It knows a Target only through the
rows written for it: a question set, a plan, a résumé.

## Decision

The current Target, and the history of Targets used, live in the browser, per
account (`web/src/features/advisorTarget.ts`).

- **The store.** `localStorage` holds `careerpolaris.target.<address>`:
  `current` (a `TargetRef`) and `history` (each Target's label and when it was
  last opened, newest first, at most 20). Every read and write is guarded, so
  storage that is unavailable or blocked behaves as an empty store.
- **What writes it.** Each of these records the Target as current and
  newest:
  - "Target this role";
  - "Set as target", even while that role is still being scored;
  - "Use again" and a Previous targets entry;
  - every time the Advisor opens on a Target.
- **What reads it.** Entering the Advisor from another screen (the sidebar,
  the header) opens the stored current Target, or "No target yet" when there
  is none (`getArrivalFocus`). It never opens the role map's selection. A hash
  that names a Target — a link, back or forward — is still honoured.
- **Previous targets.** `getPreviousTargets` joins the browser's history with
  the Targets `/gap-plans` and `/tailored-resumes` list. That way a Target
  worked on from another device still appears.
  - Each Target is dated by its latest use, plan or résumé.
  - It carries the role's fit, or a role of your own's (none while stale).
  - It leaves out the current Target, a role gone from the map, and a posting
    removed or not yet scored.
  - Switching to one only navigates: what was written for that Target loads
    as before, and nothing is posted.

## Consequences

Easier:

- No migration, table or endpoint. The rule is a front-end rule about which
  click sets the Target, and it lives in the front end.
- Picking bubbles on the map never changes what the Advisor works against.

Harder:

- The current Target is per browser. On another device, or after site data is
  cleared, the Advisor opens on "No target yet". Previous targets still lists
  every Target with a plan or résumé.
- A Target with only answers (no plan or résumé yet) is known as previous
  only in the browser that set it, because no list endpoint returns question
  sets.
- "Last used" is this browser's memory, or the last plan or résumé written.
  It is not a fact the server records.
- The hash still carries the Target, so a stale link can still open a Target
  the user has since moved away from.

## Alternatives considered

- **A `target.target_choice` table, with `GET /targets` and
  `PUT /targets/current`.** It would hold across devices and give a true
  last-used date. It lost because it needs a migration, row-level security,
  and two endpoints for what is a convenience. The rows that matter, answers,
  plans and résumés, are already on the server.
- **Keep the Target only in the hash, and stop the role map writing it.** It
  lost because the sidebar would then have no way to return to the Target,
  and Previous targets would have no history to list.
