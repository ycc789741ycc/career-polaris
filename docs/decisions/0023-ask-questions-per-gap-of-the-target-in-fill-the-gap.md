# 0023. Ask questions per gap of the Target, in Fill the gap, and submit the answers together

**Status:** Accepted — 2026-09-29. Supersedes [0012](0012-generate-follow-up-questions-when-evidence-changes.md).

## Context

ADR 0012 generated follow-up questions in the background whenever evidence
changed or an analysis finished. The questions were about the dimensions whose
confidence was below a threshold, and were shown on 01 Sources. Each answer
became `self_reported` evidence and re-ran the analysis on its own.

That asked about dimensions the user might not care about. It spent a call on
every sync, and it re-analysed after every single answer. The v3 design
(domain decision 27) moves the questions into the Advisor. Its first step,
"Fill the gap", asks about the gaps between the user's evidence and the one
role they are aiming at. The answers are submitted together, and they count
straight toward that role's gap plan and résumé.

## Decision

- **A new `advisor/gapfill` component**, between `target` and its consumers:
  `gapplan | resume | activity → gapfill → target`. It has its own schema,
  `gapfill`, under RLS, with `question_set` (keyed on the Target, with a
  status the page polls, ADR 0006) and `question`, plus a public-surface
  contract in `.importlinter`.
- **What is asked.** The Target snapshot's costliest open gaps, as the plan
  ranks them: up to four, each a `DimensionGap` (`partial`) or an `UncoveredGap`
  (`no_evidence`), with the fit points it is worth. The `gap_questions` template
  writes 1–3 questions per gap on the user's key. Each has an "asked because"
  reason, an answer type (`choice`, `free_text` or `both`) and its choices. A
  question about a gap that was not asked about fails the set, like any
  invalid output. A newer set for the same Target supersedes the older one.
- **One submit.** `POST /gap-question-sets/{id}/answers` checks the whole batch
  before storing anything: every answer must be for a question in the set, and
  a choice must be one of that question's. Blank answers are skipped, and their
  gaps stay open. Every answer is recorded through
  `profile.record_answers` in one transaction, as `user_answer` evidence with
  one `ProfileUpdated`. Each question keeps the evidence id it became. Then
  `GapAnswersSubmitted` is recorded, and the dispatcher queues
  `gapplan.regenerate` and `resume.regenerate` for that Target. Each does
  nothing if the user has no plan or résumé for it; otherwise it drafts the
  next plan version, or writes the résumé again as an `answers` version. The
  submit's price is the sum of those two.
- **Removed:** `FollowUpQuestion`, `QuestionRound`, `generate_questions`, the
  `/questions` routes, the `ProfileUpdated` branch in the dispatcher, the
  `follow_up_questions` template, `activity.request_reanalysis`, and
  `FollowUpQuestions.tsx` on Sources. Migration 0017 drops the tables, renames
  `self_reported` evidence to `user_answer` ("Your answers"), and allows the
  `answers` version source. The rule for a thin score is now
  `thin_evidence`, and it only marks a score as needing more evidence.
- **The SPA.** The Advisor opens on `#/advisor/gaps`: "First: Fill the gap →
  Then, either: Gap plan | Résumé".

## Consequences

Easier:
- Every question is about a gap the user is trying to close, and its answer
  counts toward the plan and résumé at once.
- A sync costs nothing on the key.
- Sources only lists evidence; the journey stays forward-only.

Harder:
- A user who never targets a role is never asked anything.
- Evidence gathered this way uses one role's vocabulary.
- Answers are recorded in `profile`, then linked in `gapfill`: two transactions.
  If the second fails, the answers are evidence but the questions are not yet
  marked answered. The user can submit again, which adds the answers again
  under the same question ids, so nothing is duplicated.
- Submitting rewrites the plan and résumé on the user's key without a separate
  confirmation. The submit estimate is shown next to the button instead.
- The plan's provenance line ("uses your 4 answers from Fill the gap") is not
  built yet.

## Alternatives considered

- **Keep the low-confidence questions and add per-gap ones.** Lost: two
  question flows in two places, and the first still spends on every sync.
- **Save each answer as it is typed.** Lost: every save would rewrite the plan
  and résumé, or the user would have to ask for that separately. One submit is
  one decision, with its cost shown.
- **Put the questions in `gapplan`.** Lost: the résumé regenerates from them
  too, and `gapplan` and `resume` must not import each other.
