# 0044. A résumé may claim a gap from the answers given about it, and nothing else

**Status:** Accepted — 2026-10-12.

## Context

Fill the gap (ADR 0023) asks the user about the Target's gaps, and each answer
is stored as `user_answer` evidence. ADR 0036 let a gap plan cite those
answers beside the gap they were about. The tailored résumé still could not
use them where they mattered:

- **The writer saw every answer**, as a line in the evidence block.
- **But it was told not to use them where they belonged.** `resume_write`
  said "Do not claim a requirement marked 'gap'". Coverage judges each
  requirement by the last analysis's score against the Target's bar, so the
  requirements Fill the gap asks about are exactly the ones the writer was
  told to leave out.
- **Nothing paired an answer with its requirement.** It was one line among
  every commit, issue and résumé line.
- **The rule was only in the prompt.** Nothing checked a bullet's `answers`
  against its requirement's verdict.

## Decision

An answer is evidence for the gap it was asked about, and a résumé may claim
that gap's requirement from it and nothing else.

- **Each coverage row knows its answers.** `ResumeService` takes
  `GapFillService` and reads `get_answers` once per write. A requirement's
  answers are those under its dimension's gap key
  (`gap_key_for_dimension`) or under its own statement's
  (`gap_key_for_uncovered`), whichever Fill the gap asked under; `target` now
  exports both helpers. `Coverage.answer_ids` and `CoverageView.answers` carry
  them, newest first, and the rows stored on the résumé keep them. A row
  stored before has none.
- **The prompts are told which answers go with which requirement.** The
  coverage block lists their handles: `- gap: Runs Kubernetes (answered in
  [E41])`. `resume_write` v5 and `resume_revise` v5 let a requirement marked
  gap be claimed only by lines that cite its answers and nothing else, say
  only what the answer says, and keep the old rule for a gap with none.
- **The rule is checked, not only asked for.** `assert_gap_claims_answered`
  runs on every write, every chat proposal and every filled section: a
  written line whose `answers` names a gap must cite at least one of that
  gap's answers and nothing outside them. A breach is `ai_output_invalid`, as
  a line with no citation is. A line the user wrote is theirs and is not
  checked. `get_claims_settled` first clears an `answers` that names no
  requirement of the Target, because a misnamed requirement is not an
  invented claim.
- **The verdict does not change.** Coverage is still decided by scores. An
  answered gap stays a gap until the user re-analyses; the requirements panel
  says "Answered by you" beside its verdict and lists the answers under
  Evidence.

## Consequences

Easier:

- What the user answers about a gap reaches the résumé, beside the
  requirement it is about, and Regenerate (ADR 0035) picks it up.
- A gap claim rests on something the user said about that gap, checked in
  code rather than trusted to the prompt.

Harder:

- A résumé is a document a recruiter reads. A line written from an answer is
  the user's own claim, with nothing behind it the platform has seen; the
  `user_answer` evidence is the only trail, and the rule against embellishing
  it is only in the prompt.
- The requirements panel can show a requirement as a gap while the page
  claims it. That is how coverage is decided, but it reads as a
  contradiction until the user re-analyses.
- A `req:` key is a slug of the requirement's words. A rebuild that rewords a
  requirement gives it a new key, and earlier answers no longer pair with it,
  though they stay in the evidence block.
- A line a model wrote under an older prompt that claims a gap from other
  evidence now fails a chat proposal that keeps it. The v3 and v4 prompts
  forbade such claims, so few exist.
- `resume_section` v1 is not told about coverage, yet its lines are checked:
  a section that claims a gap without its answers is refused.
- One more read of `gapfill` on every write, and `resume` needs
  `GapFillService` in its factory, as `gapplan` does.

## Alternatives considered

- **Leave the gap rule as it was and rely on a re-analysis.** Lost: the user
  answered precisely so that the résumé could speak to the gap, and a
  re-analysis is a spend they would need to know to make.
- **Count an answer toward the verdict locally** (an answered gap becomes
  partial). Lost for now: it changes what a verdict means, and through the
  fit what the role map shows; it needs its own decision.
- **Pair answers by asking the model which requirement each answers.** Lost:
  Fill the gap already records the gap each question was about; asking again
  spends the user's key on what is known.
