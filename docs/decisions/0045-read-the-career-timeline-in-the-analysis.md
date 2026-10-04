# 0045. The career timeline is the analysis's reading of the evidence

**Status:** Accepted — 2026-10-12.

## Context

The CareerProfile is "the career timeline plus the Evidence set". The timeline
had every reader it needed and no writer:

- **The résumé writer** was given `timeline` and always got "(no positions
  recorded)". It learned roles and employers only from an uploaded résumé's
  raw text, so Experience was only as good as the model's reading of that
  text, and ADR 0043 had to write Experience without roles at all when there
  was no résumé.
- **The analysis** was given the timeline and "Total experience, overlaps
  counted once" to judge seniority, and got nothing, even for a user who
  uploaded a résumé.
- **`GET /profile`** returned `positions` and `total_experience_months`,
  always empty. ADR 0039 noted the gap.

There were three places positions could come from:

- **The résumé parser.** It is local, and splits text into lines on purpose
  (decision 18: ingestion never calls a model). Reading titles, employers and
  date ranges out of free-form résumés locally is unreliable.
- **A model call on upload.** Uploading spends nothing, and must not start
  spending the user's key without asking.
- **The analysis.** It is already a spend the user confirms, already reads
  every résumé line and answer, and is the timeline's first reader.

## Decision

The career timeline is what the latest successful analysis read from the
evidence, cited to it.

- **`skill_assessment` v5 reports `positions`.** Each has `title`, `company`,
  `started_on` and `ended_on` (`YYYY-MM`, `ended_on` null for a current one)
  and `evidence_ids`. A position is reported only when a résumé line or an
  answer states it, never inferred from a GitHub organisation or a Jira site.
  The newer fact wins, as ADR 0037 has it. The prompt works the positions out
  first and judges seniority from them. It is no longer given the stored
  timeline, so a run never just confirms the last run's reading.
  `expected_output_tokens` rises from 3,500 to 4,000.
- **The positions are checked, not trusted.** Every cited handle must resolve
  to the user's own evidence, and to a `resume` or `user_answer` fact.
  `assert_position_readings_valid` (`profile.domain.timeline`) also requires
  a title, a company, a start no later than the end, and neither date in the
  future. Any breach rejects the whole reply (`ai_output_invalid`, or
  `evidence_not_owned` for an invented handle) before anything is stored, so
  a bad reading never half-lands.
- **Each successful analysis replaces the timeline.**
  `ProfileService.replace_positions(owner_id, skill_assessment_id, readings)`
  runs in the same success path that stores the assessment. A failed analysis
  never reaches it and leaves the last timeline as it was. `profile` keeps
  owning its table; `assessment` already reads `profile`, so the
  import-linter contracts need no change.
- **It is a reading, not evidence.** Replacing the timeline moves no profile
  version. A résumé or plan is outdated by the evidence that changed it, not
  by the reading that followed.
- **Migration 0040** adds `evidence_ids` (jsonb) and `skill_assessment_id` to
  `profile.position`. The id is named after the entity in full, as the
  design guideline requires, though `rolemap.role_candidate` still says
  `assessment_id`. There is no foreign key: the analysis lives in another
  component's schema. No row was ever written before, so nothing is
  backfilled.
- **Its readers are unchanged.** The résumé writer's `timeline` and
  `total_experience_months` already format and merge positions. Sources lists
  facts and nothing the analysis made of them, so the timeline is not shown
  there; `GET /profile` keeps returning it.

## Consequences

Easier:

- A user who uploaded a résumé, or answered where they worked, gets
  Experience entries with real titles and employers, from a reading that cites
  what it read.
- The analysis judges seniority from the positions it read, overlaps counted
  once.
- A wrong or invented position is refused in code before it is stored.

Harder:

- The timeline changes only when the user re-analyses. A résumé uploaded after
  the last analysis is in the evidence the writer reads, but not in the
  timeline, until then.
- A position is a model's reading. It is cited, but nothing checks it against
  the words of the line it cites, and a wrong title or date reaches the
  résumé. The user cannot correct the timeline except through an answer and a
  re-analysis.
- Every analysis costs a little more, for the positions.
- The timeline is replaced whole on every analysis. If one analysis reads
  fewer positions than the last, the ones it missed are gone.

## Alternatives considered

- **Parse positions in the résumé parser.** Lost: decision 18 keeps ingestion
  free of models, and local parsing of free-form résumés is unreliable.
- **Ask the model when a résumé is uploaded.** Lost: it spends the user's key
  on an action that has always been free.
- **Keep each analysis's positions and show their history.** Lost for now:
  nothing reads a past timeline, and keeping one reading is simpler.
- **Let the user edit the timeline.** Not yet: Sources must not show what the
  analysis made of the facts, and Strengths, where it could go, has no editor.
  An answer and a re-analysis is the correction path until then.
