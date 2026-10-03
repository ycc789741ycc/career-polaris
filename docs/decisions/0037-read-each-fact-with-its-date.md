# 0037. Read each fact with its date, and let a newer fact win over an older one it contradicts

**Status:** Accepted — 2026-10-08.

## Context

Every fact carries a date, `Evidence.observed_on`, and the date means
something different by kind:

- an `item` (one commit, one issue): when that work happened;
- a `summary` ("40 commits authored in x"): only the latest of the items it
  counts;
- a résumé line: none;
- an answer from Fill the gap: the day it was given.

The connectors used it to decide what to collect: GitHub keeps the 25 newest
commits, and Jira ranks epics by when they were last worked on (ADR 0017).
After that no prompt saw it. `skill_assessment`, `gap_plan`, `gap_questions`,
`resume_write` and `resume_revise` each got every fact as
`[handle] (source) reference: fact`, each from its own copy of the line. So:

- a skill last used five years ago weighed the same as last month's work;
- two facts that contradicted each other — an older résumé's "Junior
  developer at X" and a newer one's "Senior engineer at X", or a résumé line
  against what GitHub shows — both reached the model, with nothing to say
  which was current, and no prompt said what to do about it. A reply is
  checked only for whether a cited id exists, so a stale fact could be scored,
  planned on, or written into a résumé;
- the profile snapshot was sorted by source alone, and Fill the gap sends only
  its first 60 facts, so the facts it left out were the user's own answers,
  which sort last.

## Decision

Every prompt reads each fact with its date, says what the date means, and is
told that the newer fact wins.

- **One line, written once.** `profile.get_evidence_line(evidence, handle)`
  replaces the five copies: `[E3] (github, 2026-08-14) reference: fact`. The
  date part, `get_date_label` in `profile.domain`, says what it means:
  - a plain date for one piece of work;
  - `latest 2026-08-14` for a summary;
  - `from a résumé uploaded 2026-05-02` for a résumé line, dated by the file
    it was last found in (`EvidenceView.stated_on`);
  - `answered 2026-09-30` for an answer;
  - `undated` otherwise.

  Only the platform writes it, so no user-written text reaches that part.
- **Newest first.** `ProfileSnapshot.evidence` is ordered by the date each
  fact is shown with, undated last, ties by source then id. Any cut, such as
  Fill the gap's 60, drops the oldest facts.
- **A rule on time in every prompt that reads evidence**: `skill_assessment`
  v4, `gap_plan` v3, `gap_questions` v2, `resume_write` v2 and
  `resume_revise` v2. All of them say that a résumé's upload date or an
  answer's date is when the fact was stated, not when the work happened; that
  when two facts contradict each other the newer one wins and the older is not
  cited as current; and that an undated fact never overrides a dated one.
  Then, by prompt:
  - the analysis weighs recent work more in `score`, says in `read` how old a
    dimension's only work is and which contradiction a newer fact settled, and
    keeps `confidence` about how much evidence there is;
  - the plan treats a skill shown only by old work as a refresher, and lets an
    answer beside a gap win over an older fact about it;
  - the questions ask which fact is current when facts about a gap conflict;
  - the résumé prompts never write a superseded fact as the current state.
- **Nothing reruns by itself, and nothing is stored.** The rules apply from
  the next analysis, plan, question set or résumé the user asks for. There is
  no migration; it reverts by loading the previous template versions.
  Estimates need no change: the gateway prices the rendered prompt.

## Consequences

Easier:

- Recent work counts for more, and a contradiction has a stated winner.
- What a fact's date means is decided once, in the profile, and every prompt
  shows it the same way.
- Fill the gap keeps the user's newest facts, answers included, when a large
  profile is cut.

Harder:

- Strengths before and after `skill_assessment` v4 are not like for like. A
  dimension can drop with no new evidence because its work aged, so comparing
  two assessments can show a change that no new evidence caused.
- Recency is weighed by the model, not by a rule we can test. The same facts
  can score differently from one analysis to the next.
- A summary's date is only its latest item: "40 commits, latest 2026-08-14"
  looks current even when 39 of them are years old.
- A résumé's upload date is when it was stated. An old résumé uploaded today
  can win over last year's GitHub work if the model misreads the rule.
- An answer dated today wins over an older fact it contradicts, so a user can
  talk the analysis out of what their own sources show.
- A changed prompt does not mark a plan or résumé outdated (ADR 0035 records
  the evidence and the Target, not the prompt).
- Every prompt that reads evidence is a few tokens longer per line, on the
  user's key.

## Alternatives considered

- **Weigh recency in code, with a decay on each fact's contribution.** Lost:
  the model writes the scores from the facts' text, so a decay would have
  nothing to apply to without moving scoring out of the model.
- **Drop facts older than some cutoff.** Lost: an old skill is still a skill;
  the user should be told it is old, not have it disappear.
- **Resolve contradictions before the model sees them.** Lost for now: it
  needs a model step of its own on the user's key, and deciding which two
  facts contradict is the hard part of it.
- **Date résumé lines by the positions on the timeline.** Better, since it
  would say when the work happened, but nothing writes a `CareerPosition`
  yet, so there is no timeline to date them by. It stays open.
