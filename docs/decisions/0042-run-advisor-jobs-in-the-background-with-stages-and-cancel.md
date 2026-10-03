# 0042. Advisor jobs run in the background, record their stage, and can be cancelled

**Status:** Accepted — 2026-10-11.

## Context

The Advisor runs five kinds of short AI job, each usually under a minute:

- writing Fill the gap's questions;
- drafting a gap plan;
- writing a résumé;
- filling one of its sections;
- scoring a posting of the user's own.

Each is a row the job's own tab polled (ADR 0006). So:

- **Running out of sight.** Leaving the tab hid that a job was still
  running.
- **The page blocked.** Coming back showed the whole content area as a
  "Writing…" panel.
- **No progress.** A job had only a status, with nothing to show how far
  it had got.
- **No way to stop it.** A job could not be cancelled.
- **Not on the shell's list.** `GET /activity` knew syncs, parses, analyses
  and role-map builds only.

The prototype of 3 October 2026 (evening) draws these as **Advisor jobs**
(`GapsBuilding`, `PlanBuilding`, `ResumeBuilding`, `PlanWhileResume`):

- the tab shows a slim card with a spinner, a status line, a bar, the cost,
  Cancel, and links to the other tabs;
- the tab's name shows a spinner and "preparing…", "drafting…" or "writing…";
- the other tabs stay usable;
- "Target this role" lands on Fill the gap already preparing.

## Decision

- **A job records its stage on its row.**
  - The rows are `gapfill.question_set`, `gapplan.plan`, `resume.resume` and
    `target.posting_evaluation`.
  - Each gains `stage` and `progress` (0 to 1, never going backwards). The
    first three also gain `estimated_cost_usd`. Every status check takes
    `cancelled`. All of this is migration 0038.
  - Each component declares its stages and each stage's share of the job, in
    its `constants.py`.
    - Questions: reading, writing, checking.
    - A plan: reading, drafting, checking, saving.
    - A résumé or a section: reading, writing, checking, saving.
    - A posting: reading the file, reading requirements, scoring, working out
      the fit.
  - `kernel.progress.get_stage_progress` turns a stage and a share of it into
    progress.
- **Progress while the model writes is real or absent.**
  - `AiGateway.run(..., on_progress=)` streams the reply. It reports a
    `Progress` once before each attempt is sent, then at most every two
    seconds. The report carries the share of the template's
    `expected_output_tokens` written so far, capped at 95% until the reply
    is checked, and the call's estimated cost.
  - A posting's scoring calls through the role map's kit and reports stages
    only.
  - Nothing invents a percentage.
- **Cancel marks the row; the job stops at its next look.**
  - The routes are `POST /gap-question-sets/{id}/cancel`,
    `/gap-plans/{id}/cancel`, `/tailored-resumes/{id}/cancel` and
    `/own-postings/{id}/cancel`. Each answers 409 for a job that is not
    running, and 404 for another user's.
  - The job looks before each call, from inside the progress callback, and
    before it saves. Seeing `cancelled`, it raises
    `kernel.progress.JobCancelledError`. That is not a `DomainError`, so a
    cancel is never recorded as a failure.
  - Raised mid-stream, it stops the call where it is. What was written so far
    is still recorded in the ledger, because the provider bills for it. The
    card says so before the click.
- **What a cancelled job leaves.**
  - A cancelled plan version is in no history, and the version before stays
    current.
  - A cancelled question set leaves the Target's earlier set current: a set
    now supersedes the earlier ones when it is *written*, not when it is
    requested.
  - A résumé with a saved version goes back to it, and its plan to that
    version's sections. A first draft is `cancelled` and no longer listed.
  - A cancelled evaluation is skipped, and the run before it stands.
- **One job of a kind per Target at a time.** Requesting a second set, plan or
  résumé for a Target while one runs is a 409.
- **`GET /activity` lists them.**
  - `advisor_jobs` gives each job's kind, id, Target, label, stage, progress,
    start and estimated cost.
  - `activity` sits beside `gapplan` and `resume` and cannot read them, so the
    route gathers each component's `running_jobs` from its public API.
    `RunningJobView` is the kernel's, re-exported by `advisor.activity` for
    the schemas.
- **The SPA.**
  - The shell polls `/activity` while any job runs, and every tab reads that
    one poll.
  - `AdvisorJobCard` replaces a tab's content while its job runs.
  - The step tabs show a spinner and the job's word.
  - `AdvisorJobNotice`, in the corner on the other tabs, reads "Writing your
    résumé · 40% · View".
  - When a job ends, the plan and résumé lists are read again, and the tab
    shows its result, or its failure, as before.
- **Targeting starts the questions.**
  - "Target this role" prices writing the questions, starts them once
    confirmed, and opens Fill the gap preparing. A Target with nothing to
    ask about opens without a spend.
  - "Set as target" on a posting of the user's own prices scoring and
    questions together (`?with_questions=true`). The questions are priced as
    a ceiling until the posting is scored: `gapfill.estimate_ceiling`.
  - Once confirmed (`?write_questions=true`), the worker writes the
    questions once the scoring finishes ready: `wiring.queue.queue_questions`.
    `target` never reaches `gapfill`.

## Consequences

Easier:

- A job never takes over the Advisor. The user can edit the plan while the
  résumé is written.
- A job the user no longer wants stops before its next spend.
- The shell knows every job that runs, from one poll.

Harder:

- `GET /activity` reads four more components on every poll while anything
  runs.
- Cancelling is not a refund. A reply cut off mid-stream is billed and saves
  nothing.
- **Ledger accuracy.** A streamed job's output tokens are estimated from the
  reply's length, as the chat's always were, rather than read from the
  provider's count. The ledger is slightly less exact for those calls.
- **A narrow race.** A progress write and a cancel can cross: both read the
  row, then both write it. A cancel lost that way lets the job finish as if
  it had not been asked to stop. The job reads the row again before it
  saves, which narrows the window but does not close it.
- **One per kind per Target.** A user cannot queue a second plan for a Target
  while one drafts. They wait for it, or cancel it.

## Alternatives considered

- **Keep each tab polling its own row.** Lost: nothing outside the tab knows,
  so the spinners and the notice would need four more polls.
- **Kill the worker task on cancel.** Lost: Procrastinate cancels a job not
  yet started, but cannot stop one mid-call cleanly. A mark the job reads is
  plain and testable, and it stops a streamed call too.
- **Invent progress from elapsed time.** Lost: a bar that moves without
  anything happening is a lie the user notices on a slow model.
