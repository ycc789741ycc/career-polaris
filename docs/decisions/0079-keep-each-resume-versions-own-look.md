# 0079. Keep the look a résumé version was saved in, and print it in that look

**Status:** Accepted — 2026-10-12. Amends [0038](0038-export-the-resume-as-previewed-and-download-it.md), [0075](0075-let-a-resume-set-its-headings-font-bold-titles-and-text-size.md) and [0078](0078-keep-the-text-settings-to-the-text-and-size-titles-and-headings.md).

## Context

A résumé's look — its template, built in or of the user's own, the fonts,
bold switches and sizes it sets over it (ADR 0047, 0075, 0078), and "Trim to
one page" — was kept on the résumé alone, and saved the moment it changed
(`PUT /tailored-resumes/{id}/settings`). A version kept only its content. So
an older version opened from the Version list showed in today's look, and its
export printed in today's look (ADR 0038: "in the résumé's look and trim as
they are now"). Users asked that the layout and fonts they chose be recorded
when they save, as the text is.

## Decision

- **A look change is part of the draft.** Changing the template, a font, a
  Bold switch, a size or the trim previews at once and is an unsaved edit, as
  Show/Hide and moving a section have been since Phase 11: Undo takes it back,
  it enables "Save as vN", and Export and filling a section wait for the save.
  Quantify and Reorder skills steer the writing rather than the print, so they
  stay the résumé's own and are still kept at once.
- **Each version keeps its look.** `ResumeVersion.look` is a `VersionLook`:
  one template (`template` or `custom_template_id`, exactly one), an `OwnLook`
  and `trim`, stored as JSONB in `resume.version.look` (migration 0060).
  `POST /tailored-resumes/{id}/versions` takes the draft's `look`; left out,
  the save keeps the latest version's. A look naming a template that is not
  the user's, or a font or size out of range, is refused before anything is
  saved.
- **The résumé mirrors its latest version.** Saving a version lays its look on
  the résumé row, in the same transaction. Everything that reads the row —
  the Version list, regenerating, a job's new version, which takes the row's
  look — keeps working unchanged.
- **A version prints in its own look.** `request_export` renders the spec and
  trim of the version asked for, not the résumé's. Reusing an export still
  compares spec and trim.
- **A template is named, not referenced.** No foreign key points from a
  version to a template of the user's own. Deleting one leaves a version saved
  in it to read and print as Organic with its own fonts and sizes kept, as the
  résumé row already moves to Organic.
- **Older versions take their résumé's look.** Migration 0060 backfills every
  version stored before it from its résumé's look as it stood, so nothing
  prints differently the moment after.

## Consequences

Easier:

- An older version opened, exported or saved again is the page it was.
- Trying a look is undoable and costs nothing until it is saved.

Harder:

- A look change is lost if the user leaves without saving, where before it
  was kept at once.
- Every version carries a copy of its look, and the look is now in two places
  — the row and its latest version — kept equal by saving through one path.
- Versions saved before migration 0060 all claim the look their résumé had
  when it ran, which may not be the look each was first printed in.
- `PUT /settings` still sets the row's look, so a client that uses it for the
  look makes the row differ from its latest version until the next save; the
  SPA sends it only for Quantify and Reorder, with the saved look.

## Alternatives considered

- **Keep the look live and copy it onto each save.** Lost: opening an older
  version would have had to change the résumé's look at once, and an unsaved
  change would still print in an export of an unchanged version.
- **Twelve columns on `resume.version`.** Lost: they would only repeat what
  the résumé row already checks; the save validates the look before storing
  it, and JSONB keeps the version table one column wider rather than twelve.
- **A foreign key to the user's own template.** Lost: deleting a template
  would then have to rewrite or block every version saved in it; reading a
  missing one as Organic is what the résumé row already does.
