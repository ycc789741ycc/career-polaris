# 0035. Regenerate the gap plan and résumé only when the user asks, and say when they are outdated

**Status:** Accepted — 2026-10-08. Amends [0023](0023-ask-questions-per-gap-of-the-target-in-fill-the-gap.md).

## Context

ADR 0023 decided that one submit in Fill the gap records every answer as
`user_answer` evidence and emits `GapAnswersSubmitted`, and that the
dispatcher then queues `gapplan.regenerate` and `resume.regenerate`. Each
rewrote the Target's plan or résumé on the user's key, if one existed. The
price was shown next to Submit (`GET /gap-question-sets/{id}/submit-estimate`).

That made answering a question a spend:

- A user could not answer now and rewrite later, or answer a second set first
  and rewrite once.
- It was the only spend in the journey the user did not ask for on its own.
  An analysis, a role-map build, setting a posting of your own as the target
  and writing questions are each confirmed separately.
- Answers are not the only thing a plan or résumé reads. A sync, a résumé
  upload, a re-analysis or a rebuild changes what they read too, and none of
  those rewrote anything or said anything.

## Decision

Nothing rewrites a plan or résumé by itself. Each records what it read, and
the Advisor says when that has moved on.

- **Submitting spends nothing.** `GapAnswersSubmitted` is still recorded, and
  the dispatcher queues nothing for it. The `gapplan.regenerate` and
  `resume.regenerate` tasks, the services' `regenerate`, the submit estimate
  and `SubmitEstimate` are gone. `VersionSource.ANSWERS` stays for versions
  written before this.
- **A draft records what it read**, as a `DraftBasis` in `target.domain`:
  - `profile_version`, from the `ProfileSnapshot` the draft read;
  - `target_digest`, from `get_target_digest(TargetSnapshot)`, a hash of the
    requirements (statement, weight, expected level), the basis, the fit,
    the dimension gaps and the uncovered requirements. It leaves out
    `taken_at`, the label and the order anything was loaded in.

  A gap plan stores it when its draft finishes, and a tailored résumé each
  time a version is generated. A manual edit or an applied chat revision
  reads neither, so it leaves the basis alone. Migration 0033 adds both
  columns, nullable, to `gapplan.plan` and `resume.resume`.
- **Outdated is worked out on read, and spends nothing.**
  `TargetService.get_outdated_reasons` compares the recorded basis with the
  profile version now and the Target as it resolves now, and answers
  `evidence`, `target`, both or neither. Only a ready résumé, and only the
  Target's latest ready plan version, is judged. A draft from before bases
  were recorded is unknown, never outdated. A Target that cannot be resolved
  now — not scored since a rebuild, or gone — counts as changed.
  `PlanView`/`Plan` and `ResumeView`/`TailoredResume` carry `is_outdated` and
  `outdated_by`.
- **Regenerating is a request with a confirmed cost.** A plan already
  regenerates as a new version through `POST /gap-plans`, priced by
  `/gap-plans/cost-estimate`. A résumé gets
  `POST /tailored-resumes/{id}/regenerate` (202), priced by
  `/tailored-resumes/cost-estimate`. It redrafts the same résumé and queues
  `resume.generate`, which saves its next version as `generated`. A résumé
  already being written answers 409.
- **The SPA.** Submit in Fill the gap shows no cost and says it spends
  nothing. The plan and résumé tabs show "Outdated: your evidence changed",
  "Outdated: the target changed", or both, with a Regenerate button that
  prices the rewrite first.

## Consequences

Easier:

- Answering is free and can be done in any order, as often as the user likes.
- Every spend in the journey is one the user confirmed on its own.
- Any change to what a plan or résumé read — a sync, an upload, a
  re-analysis, a rebuild — is now visible, not only answers.

Harder:

- A user who answers and never regenerates keeps a plan and résumé that
  ignore those answers. The banner is the only thing that tells them.
- The digest decides what counts as a change. A new plan or résumé prompt,
  or a change to the fit rules outside what the snapshot carries, marks
  nothing outdated.
- Any evidence change marks every plan and résumé outdated by `evidence`,
  even one that does not touch that Target. Telling them apart would need
  the cited evidence, not a version number.
- Two more columns on two tables, and on every read of a plan or résumé a
  profile-version read and a Target snapshot, to compare against.

## Alternatives considered

- **Keep regenerating on submit, priced next to Submit (ADR 0023).** Lost
  because answering stayed a spend the user could not separate from the
  rewrite, and because every other change of evidence still went unseen.
- **Regenerate automatically after any change of evidence or Target.** Lost
  for the same reason, many times over: a sync would spend the user's key.
- **Track the cited evidence instead of a profile version.** It would mark a
  plan outdated only when evidence it relies on changed. Lost for now:
  evidence that was not cited can still change what the model would write,
  and a version number is one integer to compare. It stays possible later.
- **Store the whole snapshot and compare field by field.** The plan already
  keeps its snapshot, but the résumé's is the one it was written against,
  which a manual edit does not refresh. A digest is cheaper to compare and
  says the same thing.
