# 0015. Remove a résumé's evidence with it, and mark every report the profile has moved past as out of date

**Status:** Accepted — 2026-09-28.

## Context

Evidence left the profile in only one way: disconnecting GitHub or Jira
deleted every fact from that source. An uploaded résumé could not be removed
at all, so its file, its row and every line parsed from it stayed forever, and
each upload added its lines on top of the last.

Removing evidence, or adding it, also changed nothing on the strength report.
Each `SkillAssessment` records the `profile_version` it read, so that "a stale
one can be detected" (domain section 2.4), but nothing compared it with the
profile. The Connect page compared the two in the browser for one sentence
under the evidence table; the report itself said nothing, and went on showing
scores that cite facts which no longer exist.

Résumé lines are keyed by `resume:{filename}:{line}` so that uploading the same
file again restates its facts rather than duplicating them. A restated fact
kept the `resume_file_id` of the first upload that stated it.

## Decision

**Deleting a résumé deletes the file and every fact it owns**, in
`ProfileService.delete_resume`, behind `DELETE /resumes/{id}`. The stored
object is deleted first, because deleting an object is idempotent: if the
database step then fails, trying again completes it. The facts, then the row,
are deleted in one transaction, which bumps the profile version and records
`ProfileUpdated` for the `resume` source, exactly as a disconnect does. The
dispatcher then opens a fresh round of follow-up questions (ADR 0012) and, as
before, starts no analysis.

**A fact belongs to the newest résumé that states it.** When a later upload
restates a line, `Evidence.found_in_resume` moves the fact to that upload. So
removing an older copy keeps what the newer one still says, and removing the
newest takes it away.

**An assessment is out of date whenever the profile version has moved past the
one it read.** `AssessmentView.is_out_of_date` is decided on the server, in
`latest` and `history`, and sent on the wire. Every change to evidence bumps
the version — a sync, an upload, an answer, a disconnect, a deleted résumé —
so any of them puts every earlier report out of date. A sync that restates
identical facts counts too: the rule is "the sources were updated", not "the
facts differ". The strength report shows a notice, the Connect page reads the
same flag instead of comparing versions itself, and a re-analysis clears it.

## Consequences

- Easier: a user can take a wrong or old résumé off their profile, and the
  report says plainly when it no longer matches the evidence behind it.
- Easier: one rule, on the server, decides "out of date"; the SPA no longer
  needs the profile's version to know.
- Harder: removing the newest of two uploads of the same file removes those
  lines, although the older copy still contains them. Getting them back means
  uploading again. We accepted this rather than re-parsing the remaining files
  on every delete.
- Harder: a re-sync that finds nothing new still marks the report out of date,
  so a user who syncs often will see the notice often. Detecting "nothing
  changed" would mean comparing every restated fact, and a report is only as
  current as the sources were when it ran.
- Harder: a report still cites the ids of facts that have since been removed.
  The notice says the report is out of date; it does not mark which citations
  are gone.
- A deleted résumé cannot be restored. The confirmation step in the SPA is the
  only guard.

## Alternatives considered

- **Keep a deleted résumé's facts, unlinked** (what `ON DELETE SET NULL` on
  `evidence.resume_file_id` would do with a bare row delete). Lost because the
  facts would go on backing scores after the user removed the document that
  was their only evidence.
- **Key résumé lines by upload, not by filename.** Every upload would own its
  own lines, so deletion would be exact, but uploading the same file twice
  would double every fact, which is the duplication the filename key exists to
  prevent.
- **Mark a report out of date only when the facts it cites change.** More
  precise, but a new source can move a score without touching any fact already
  cited, so this would miss the change that matters most. Lost to the simpler
  rule the user asked for.
- **Keep comparing versions in the SPA.** Lost because every screen that shows
  a report would need the profile's version and the same comparison, and the
  report page never had it.
