# 0073. Score an opening Target with AI when its gap analysis runs, started only from the Advisor

**Status:** Accepted — 2026-10-11. Supersedes [0032](0032-work-out-every-openings-fit-locally-from-its-roles.md). Amends [0042](0042-run-advisor-jobs-in-the-background-with-stages-and-cancel.md) and [0070](0070-let-an-opening-on-the-role-map-be-picked-as-the-target.md).

## Context

"Target this role" and "Target this opening" on 03 Roles did two things at
once. They aimed the Advisor, and they priced and started writing the
Target's gap questions (ADR 0042, kept by ADR 0070). Aiming the Advisor
therefore spent the user's key or the platform's quota, from a screen whose
job is choosing. Fill the gap could already start the same run with "Write
questions", but it was never reached empty from the map.

An opening's fit was never its own. Since ADR 0032, every build worked out
each opening's fit from its role's AI fit, locally. It reweighted the role's
requirements by each one's embedding similarity to the opening, centred on
the role's mean. The Advisor's "Fit today" for an opening, its questions, its
gap plan and its résumé all read that derived fit. It measured the user
against the role's requirements, reweighted, not against what the posting
says. Two openings in one role whose descriptions ask for different things
could not differ by a requirement the role did not have.

## Decision

The role map only aims, and an opening Target is scored with AI, from its
own description, when its gap analysis runs.

- **The role map only aims.** "Target this role" / "Target this opening"
  records the Target (ADR 0050) and opens Fill the gap. Nothing is priced,
  confirmed, queued or spent.
- **The gap analysis starts in Fill the gap.** The empty state is "No gap
  analysis yet", with "Analyse the gaps". For a role it writes the questions,
  as before. For an opening it runs one gapfill job in two stages:
  - `scoring_target`: the opening is scored, unless its fit is current.
  - Then the questions are written for its gaps.
  - One estimate covers both: the scoring, plus the questions priced as a
    ceiling, since the gaps are not known yet. It is confirmed once on the
    user's own key, and starts at once on CareerPolaris AI (ADR 0067).
- **An opening's fit is read from its own posting.** It is scored as a
  posting of the user's own is (ADR 0034), with the role map's fit kit:
  - `extract_requirements` reads what its description asks for, once.
  - `project_requirements` maps that onto the user's dimensions.
  - `get_posting_fit_result` works out the score and gaps locally.

  Three owner-zone tables in `target`, under RLS and keyed on the shared
  posting's id, keep it:
  - `opening_requirement`;
  - `opening_requirement_fit`;
  - `opening_fit`.

  The requirements read outlive the posting. After a newer analysis the fit
  is stale; the next gap analysis rescores it (the projection only).
- **A fit from embedding similarity is never shown or used.** Builds no
  longer compute opening fits:
  - `_derive_opening_fits`, `get_requirement_relevance`, `get_opening_fit`,
    the `OPENING_*` constants and `rolemap.posting_fit` are gone (migration
    0056).
  - `GET /matched-postings` gives every opening its role's fit, and
    `fit_basis` is gone.
  - Before its gap analysis, an opening Target shows "Fit today —".
  - Its snapshot refuses with `target_unusable` ("run its gap analysis in
    Fill the gap first").
  - The gap plan and résumé tabs say so, unless something was drafted for
    it already.
  - `GET /opening-fit?job_posting_id=` serves the fit once scored.
- **A role Target, and a posting of the user's own, are unchanged.** A role's
  fit is still its build's. A posting of the user's own is still scored by
  "Set as target".

## Consequences

Easier:

- Choosing a target on the map is free and has no confirmation, so trying
  targets costs nothing.
- An opening is measured against what its posting asks for. Two openings in
  one role can differ by requirements the role never named.
- Builds do less: no opening fits, no requirement embeddings, and no vector
  read per opening after `compute_fits`.
- One way to score a posting against the user, whether it is an opening or
  one of the user's own.

Harder:

- An opening costs two AI calls the first time its gap analysis runs (a read
  and a projection), and one after each new analysis. These were free before.
- "Fit today" is blank for an opening until its analysis runs. The gap plan
  and résumé for an opening need that analysis first: one more step before a
  plan.
- An opening's fit can differ from its role's more than a reweighting ever
  made it, with nothing on the map explaining why.
- The estimate for an opening is a ceiling, since its gaps are unknown until
  it is scored.
- Plans and résumés drafted against a derived fit now read as outdated by
  the target, because their target digest changes.
- Opening fits stored before migration 0056 are dropped. Nothing is moved
  across, since a derived fit is not an AI fit of the opening.

## Alternatives considered

- **Keep the derived fit as a free estimate until the analysis runs.** Lost:
  a number from embedding similarity next to one from AI reads as the same
  kind of claim. The user asked never to be shown it.
- **Score an opening when "Target this opening" is pressed.** Lost: that is
  the spend on the map this decision removes.
- **Add a nullable `job_posting_id` to the own-posting tables.** Lost: each
  of the three tables and their filters would carry two exclusive keys. The
  own-posting code assumes `private_job_posting_id` throughout, and its
  removal path would have to tell the two apart. Separate tables cost three
  mappers and repositories, and keep each path plain.
- **Score the opening as a separate job, then queue the questions (as "Set
  as target" does).** Lost: two jobs, two cards and two cancels for one
  button. One gapfill job with a scoring stage is one card, one cancel and
  one estimate.
