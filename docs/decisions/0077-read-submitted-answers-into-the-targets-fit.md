# 0077. Read submitted answers into the Target's fit, in the Advisor only

**Status:** Accepted — 2026-10-12. Amends [0035](0035-regenerate-the-plan-and-resume-only-when-asked.md).

## Context

Fill the gap asks about the Target's costliest gaps, and one submit stores
every answer as `user_answer` evidence. ADR 0035 made that submit spend
nothing: no plan or résumé is rewritten, and they say they are outdated.

But the Target's fit did not move either. A fit is arithmetic over the
dimension scores of the user's latest analysis (`get_posting_fit`): a gap
closes only when a new analysis rescores the dimension, and an uncovered
requirement, mapped to no dimension, stays uncovered until then. So after
answering, "Fit today", the gaps the plan ranks and the coverage the résumé
shows all ignored the answers, until the user re-analysed on 02 Strengths and
rebuilt the map. Users asked for the fit to follow their answers.

## Decision

- **One call per submit.** With `update_fit` (the default), a submit records
  the set as reading (`QuestionSet.fit_reading`) and queues
  `gapfill.read_answers` on the `ai` queue, an Advisor job like the others
  (ADR 0042): `GET /activity` lists it as `fit_update`, with its stage and
  Cancel. The call (`answer_reading` v1) is given each gap this set answered,
  what the analysis made of it, and every answer given about it for the
  Target, dated. Per gap it returns a dimension's score with the answers taken
  into account, 0–100, or an uncovered requirement's coverage, `covered`,
  `partly` or `not`, with one sentence and the answers it rests on.
- **Checked, and dropped one by one.** `get_readings_settled` keeps a reading
  only for a gap that was answered, with what its kind needs, citing only that
  gap's answers; the first reading of a gap wins. Anything else is dropped and
  counted in the log, not the whole reply (as ADR 0074 does for a plan).
- **Kept by `target`.** `target.answer_reading` (RLS, migration 0058) holds
  each reading with its Target, its set, and the analysis it was taken
  against. `gapfill` hands them over through
  `TargetService.record_answer_readings`; `target` never imports `gapfill`.
- **The fit, worked out again locally.** `get_answered_snapshot` lays the
  newest reading of each gap over the Target's snapshot, by the fit's own
  arithmetic: closing part of a dimension gap gains that share of its lift (or
  loses it when the answer shows less), a covered requirement gains its lift
  and leaves the gaps, a partly covered one keeps half its weight and half its
  lift. The fit stays 0–100 and the snapshot keeps `answered_from`. A reading
  counts only while its analysis is the latest: a new analysis reads the
  answers as evidence itself.
- **Everything in the Advisor reads it.** `TargetService.snapshot` applies it
  by default, so the questions' next gaps, the plan's ranking, the résumé's
  coverage and the outdated banner (the fit is in the target digest) all see
  it. `GET /answered-fit` gives the fit before and after and the gaps that
  moved; the banner shows "Fit today 86% → 91%", and Fill the gap lists each
  gap's change and reason.
- **Not the role map.** `rolemap`'s fits are untouched: 03 Roles never reads
  from 04 Advisor, so its bubbles move only on a rebuild after a new analysis.
- **Priced like any AI work.** `GET /gap-question-sets/{id}/fit-reading-
  estimate` prices it before the submit, as a ceiling (every question answered
  at full length). On the user's own key `CostConfirm` shows it; on
  CareerPolaris AI it just runs (ADR 0067). "Submit without updating fit"
  stores the answers and spends nothing, as before. A failed or cancelled
  reading leaves the answers stored and the fit as it was, with "Update fit"
  (`POST /gap-question-sets/{id}/fit-reading`) to run it again.

This amends ADR 0035: submitting answers still rewrites nothing, but by
default it now spends one call, which the user confirms on their own key.

## Consequences

Easier:

- Answering moves the fit at once, and the plan and résumé drafted next stand
  on it.
- The user sees what each answer was worth, gap by gap.

Harder:

- A self-reported answer can now raise a score without an analysis. The
  reading is the model's judgement of the answer, held to citing it; the
  analysis remains the record, and the next one replaces every reading.
- The Advisor's fit and the role map's can differ for the same role until the
  next analysis and rebuild, and the banner says "with your answers" to show
  which it is.
- Submitting is no longer free on the user's own key unless they choose
  "Submit without updating fit".
- One more job kind, table and prompt to keep.

## Alternatives considered

- **Re-run the whole analysis after each submit.** Lost: it costs a full
  analysis, rescores every dimension rather than the gaps answered, and marks
  the role map behind the strengths each time.
- **Move the role map's fit too.** Lost: the journey runs forward (Sources →
  Strengths → Role map → Advisor); a later step changing an earlier one would
  make the map's numbers depend on which role was aimed at.
- **Work it out with no AI**, from choice answers alone. Lost: most answers
  are free text, and a choice ("Yes") says nothing of how much.
- **Cap a reading at the target's bar.** Not needed: exceeding the bar earns
  nothing in the fit's arithmetic, so a higher score changes nothing.
