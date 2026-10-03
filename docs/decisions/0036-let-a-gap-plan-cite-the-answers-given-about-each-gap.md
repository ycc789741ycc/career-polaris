# 0036. Let a gap plan cite the answers given about each gap, including an uncovered requirement

**Status:** Accepted — 2026-10-08. Amends [0023](0023-ask-questions-per-gap-of-the-target-in-fill-the-gap.md).

## Context

Fill the gap asks questions about a Target's gaps, and each answer becomes
`user_answer` evidence (ADR 0023). Each `GapQuestion` keeps the gap it was
asked about (`gap_key`) and the evidence its answer became (`evidence_id`). A
plan drafted afterwards sees the answers, because a draft reads the profile
again. But the answers barely reached the plan:

- **The model did not know which answer was about which gap.** Each answer
  was one more line in the evidence block, among every commit, issue and
  résumé line.
- **An uncovered requirement (`req:`) cited nothing.** `gap_plan` v1 said such
  a gap "has no evidence behind it by definition; cite nothing for it". The
  questions Fill the gap asks about exactly these gaps could never be cited
  where they applied.
- **That rule was only in the prompt.** `assert_draft_valid` required a
  citation on a `dim:` gap and checked nothing on a `req:` gap, so any
  evidence id the user owned would have passed there.

## Decision

An answer is evidence for the gap it was asked about, and an uncovered
requirement may cite it — and nothing else.

- **`gapfill` says which answers are about which gap.**
  `GapFillService.get_answers(owner_id, ref)` returns `GapAnswerView`s
  (`gap_key`, `evidence_id`, `answered_at`) for every answered question in
  any of the Target's sets, newest first, leaving out an answer whose
  evidence is gone. `gapplan` already sits above `gapfill`; its factory now
  takes a `GapFillService`.
- **The prompt pairs answers with gaps.** In `gap_plan` v2's gaps block, a
  gap with answers lists their handles: `… (worth 25 fit points; answered in
  [E2])`, for `dim:` and `req:` gaps alike. The answers stay in the evidence
  block, so their text is there to read.
- **`gap_plan` v2's rules.** A `req:` gap cites only the answers listed beside
  it, or nothing. A `dim:` gap cites from the evidence block as before. When
  an answer says the person already does what a gap asks for, its `why` says
  so and that a re-analysis will count it, and the gap need not get a task.
- **The rule is checked.** `assert_draft_valid` takes `answers_by_gap`, the
  answers' handles per gap. A `req:` gap citing anything outside its own
  answers is a `PlanInvalidError`, as an unexplained gap is.
  `assert_citations_exist` still runs over every citation afterwards.
- **What is shown.** A `req:` gap's stored evidence lists the answers it
  cites, as a `dim:` gap's does, so the plan tab shows "Your answer" under
  the requirement with no change to the schema or the SPA.

## Consequences

Easier:

- The questions asked about an uncovered requirement now land where they
  were asked: its explanation can rest on what the user said.
- A citation on an uncovered requirement is enforced, not only asked for.

Harder:

- An answer can explain away a gap the plan still lists, at the same score
  and worth the same fit points, until the user re-analyses. The `why` says
  so; the ranking does not change.
- An answer is the user's word, not their work. A gap explained by one has
  weaker support than one explained by a commit, and the plan shows the
  difference only through the "Your answer" label.
- A `req:` key is a slug of the requirement's statement. A rebuild that
  rewords a requirement gives it a new key, and earlier answers are no longer
  listed beside it, though they stay in the evidence block.
- Every draft reads `gapfill` once more.

## Alternatives considered

- **Leave the pairing to the model.** The answers are in the evidence block
  already, and the model could match them by their text. Lost because the
  rule against citing anything else on a `req:` gap could then not be
  checked: nothing would say which ids were its own.
- **Let a `req:` gap cite any evidence.** Lost: a requirement is uncovered
  because nothing in the user's work maps to it, so any other citation is the
  model contradicting the fit it was given.
- **Count the answer toward the fit at once, marking the requirement covered
  at low confidence.** It would move the ranking without a re-analysis. Lost
  for now: it changes what a fit means, and would need its own decision.
