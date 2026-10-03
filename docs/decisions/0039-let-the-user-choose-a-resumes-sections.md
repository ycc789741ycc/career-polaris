# 0039. A résumé is an ordered list of sections the user chooses

**Status:** Accepted — 2026-10-08.

## Context

A tailored résumé always had the same three sections, in the same order:
summary, experience and skills. `ResumeContent` had a field for each, and the
write prompt, the revise prompt, the renderer and the preview all assumed
those three. A user could not leave one out (skills, which some people would
rather show through their work), add one (side projects, education,
certifications), or change the order (side projects ahead of skills for a
first job).

Side projects matter most: GitHub evidence is often personal work that belongs
to no position, and could only be pushed into a role it was not part of, or
left out.

The prototype of 3 October 2026 (`prototype/screens/Resume.dc.html`, domain
spec §6.3) draws a **Sections** panel: the sections in order, each with a drag
handle and Remove, Experience "Required"; "Add a section" offering Education,
Talks & writing, Open source, Certifications and Custom…; and "New sections
are filled from your sources; add or edit lines in place."

## Decision

A résumé is a header and an ordered list of sections, in a new
`resume/domain/section.py`.

- **Kinds and shapes.** `SectionKind` is summary, experience, side projects,
  open source, education, talks and writing, skills, certifications, or
  custom. Each kind has one shape: text (summary); entries — title,
  organisation, when, a link shown as text, bullets — (experience, side
  projects, open source, education, talks and writing); a list of short items
  (skills, certifications); or bullets under the user's heading (custom).
- **Rules.** Experience is always there, once; every other kind at most once;
  up to three custom sections, each with its own heading; nine in all. Every
  bullet keeps its citations, origin and answered requirement wherever it
  sits, so `assert_written_lines_cited`, `mark_edits` and `settle_revision`
  walk every section. The old limits apply per shape.
- **Stored versions moved.** Migration 0035 rewrites every saved version's
  content and every stored chat proposal from the three fields into
  sections, in the old order, and adds `resume.section_plan`. `from_dict`
  reads only the new shape.
- **The plan.** `Resume.section_plan` is the sections every new version is
  written to. Every version saved — by hand, from the chat, or generated —
  sets it to that version's sections, so moving or removing a section is an
  edit saved as a version, with no AI call. A new résumé starts with summary,
  experience and skills. Regenerating writes to the plan: a removed section
  stays removed, and one the reply lacks is kept, empty.
- **The prompts.** `resume_write` v3 and `resume_revise` v3 answer in
  sections. The write prompt is given the plan; the revise prompt adds or
  removes a section only when the person asks. A section the evidence does
  not support is left empty, never filled with invented lines.
- **Adding a section fills it from the sources.** It is priced
  (`GET /tailored-resumes/{id}/sections/estimate`) and confirmed;
  `POST /tailored-resumes/{id}/sections` adds it to the plan, sets the résumé
  `filling`, and queues `resume.fill_section`. That job writes that section
  only (`resume_section` v1), keeps every other line, and saves the next
  version; one the evidence cannot fill is saved empty. A failure leaves the
  résumé ready, with the reason.
- **The renderer and the preview draw sections** by shape, trimming bullets
  per entry and items per list. An empty section prints nothing; the preview
  says so and offers a first line to edit.

## Consequences

Easier:

- Side projects, education, certifications and the user's own headings have a
  place, and a section can go or move with one click and no spend.
- A new kind of section is one entry in `SectionKind` with a shape the
  renderer already draws.

Harder:

- Every part that reads a résumé — two prompts, the renderer, the preview,
  the chat's proposals — walks a list of kinds instead of three fields.
- A user can remove what the job screens for, such as skills; coverage still
  shows those requirements, but nothing stops it.
- A custom section's heading is the user's text, shown on the page and sent
  to the model; it is escaped and passed as untrusted.
- Adding a section is a spend, though the prototype's copy reads as if it
  were free; the price is shown before anything runs.
- Migration 0035 rewrites JSON in place. Its downgrade keeps only summary,
  experience and skills; any other section is lost on a downgrade.
- Positions are never written to the timeline, so a new résumé cannot tell
  side work from job work by itself; side projects are added by the user.

## Alternatives considered

- **Keep three fields and add optional ones.** Every new kind would be a new
  field in every reader, and the order could still not change.
- **Free-form sections (a heading and markdown).** Lost: a line must stay a
  bullet that cites its evidence, which free text cannot guarantee.
- **Fill an added section by regenerating the whole résumé.** Lost: it would
  rewrite lines the user had edited, and cost a full write.
- **Start a new résumé with side projects whenever GitHub has work outside
  every position.** With no positions on the timeline every repository is
  "outside", so it would add the section for everyone. Left to the user.
