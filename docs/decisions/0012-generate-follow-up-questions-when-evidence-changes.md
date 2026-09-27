# 0012. Generate follow-up questions in the background when evidence changes

**Status:** Accepted — 2026-09-27.

## Context

Follow-up questions exist to raise the confidence of the skill report: they
are asked about dimensions whose confidence is below
`ASSESSMENT_CONFIDENCE_THRESHOLD`, and each answer becomes self-reported
evidence. Until now they were written only inside an analysis, in the same
job, so a sync or a résumé upload never changed them until the user pressed
"Analyze" again. The Clarify page also had no way to show that questions were
being written, and could not tell "nothing to ask" from "not written yet".

Domain model section 2.11 deliberately keeps a sync from starting an analysis,
because every analysis spends the user's money. Section 2.10 allows "later
incremental runs … automatically within the budget".

## Decision

Evidence changing opens a **question round**, and only a question round: the
radar is not re-scored.

- The outbox dispatcher handles `ProfileUpdated` for every source except
  `self_reported`. It calls `AssessmentService.request_questions`, which opens
  a round only when an assessment exists and at least one of its dimensions is
  below the threshold, and queues `assessment.generate_questions` on the `ai`
  queue.
- An answer (`self_reported`) is skipped there, because its route already
  re-runs the analysis. An analysis no longer writes questions inline: the
  `assessment.run` job requests a round when it finishes, through the same
  path.
- A round is a row in `assessment.question_round`, created `generating` before
  its job runs, and set to `ready` or `failed` with the error's stable code
  (ADR 0006). The Clarify page polls `GET /questions/status` and shows a status
  bar while it is `generating`.
- A newer request marks a round still generating `superseded`. That round's job
  stops before calling the model, or drops what the model returned, so only
  one set of questions is written.
- A ready round retires the earlier questions nobody answered. Answered
  questions are kept.

## Consequences

Easier:
- New evidence brings the questions up to date without an explicit analysis,
  and the page says when they are being written and why they could not be.
- One generation path for both triggers, so the status covers the answer →
  re-analysis loop too.
- Questions stop piling up across rounds.

Harder:
- Every sync, résumé upload and disconnect now spends a small amount on the
  user's key: one questions call, capped by their budget like any other job.
  Before, a sync spent nothing.
- The questions can target a radar that is out of date. They ask about the
  latest assessment's thin dimensions using today's evidence, and a new source
  may already settle a question until the user re-analyses.
- One more job-produced table with `status`, `error_code` and `error_message`,
  and another page polling every two seconds while work runs. A job killed
  before its failure handler leaves the round `generating`, and the page keeps
  its status bar up until the next round supersedes it. There is still no
  sweeper (ADR 0006).
- Syncing two sources back to back can spend the key on a round that is then
  superseded, if the first job already reached the model.
- Nothing before the first analysis: a new user sees no questions until they
  run one.

## Alternatives considered

- **Re-run the whole analysis on every evidence change.** It would keep the
  radar and the questions consistent, but it costs several times more per sync
  and reverses the explicit-Analyze rule outright, not just for questions.
- **Keep questions inside the analysis only.** Costs nothing new, but questions
  go stale after every sync, and the page still cannot show that work is
  running.
- **Keep every round's open questions.** Simpler, but syncing GitHub and then
  Jira would ask about the same dimension twice.
