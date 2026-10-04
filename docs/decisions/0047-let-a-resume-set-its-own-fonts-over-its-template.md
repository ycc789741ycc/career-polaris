# 0047. A résumé may set its own fonts over its template's

**Status:** Accepted — 2026-10-13.

## Context

ADR 0040 made a résumé's look a checked `TemplateSpec`, including its two
fonts, chosen from the bundled `TEMPLATE_FONTS`. The only way to change a
résumé's fonts was to make a template of one's own ("Make your own"): open
the editor, pick the fonts, name and save a template, and set the résumé in
it. A user who only wanted the titles in a serif had to do all of that, and
keep a template for it.

## Decision

A résumé may set its two fonts directly, over whichever template it is set
in.

- **Stored on the résumé.** `TailoredResume.heading_font` and `body_font` are
  each `None`, keeping the template's, or one of `TEMPLATE_FONTS`
  (`assert_fonts_valid`). Migration 0041 adds the columns, with a check
  constraint on each.
- **Set with the template and options.** `PUT /tailored-resumes/{id}/settings`
  takes `heading_font` and `body_font` beside `template` and `options`. Left
  out or null, they go back to the template's. A font the résumé cannot set is
  a 422 at the schema, and a `ValidationError` in the service.
- **One look everywhere.** `get_spec_with_fonts` lays the résumé's fonts over
  its template's spec. `_spec_of` uses it, so an export renders the fonts and
  stores them in its `spec`, and reuse (ADR 0038) tells a re-fonted export
  from the last. The preview lays the same fonts over the chosen template's
  look.
- **Templates are untouched.** Picking another template keeps the résumé's
  fonts. A template of one's own still carries its own fonts, which the
  résumé's override as for a built-in one.
- **The SPA.** Two selects in the Template panel, "Titles in" and "Text in".
  The first option, "Template's (…)", names the template's font and means
  null.

This amends ADR 0040: a résumé's look is its template's spec with the
résumé's own fonts, if it set any.

## Consequences

Easier:

- Changing a résumé's fonts is one choice, with no template to make or keep.
- The preview, the PDF and export reuse all read the same look.

Harder:

- A résumé's look now has two sources, its template and its own fonts. A user
  who edits a template's fonts sees no change on a résumé that set its own.
- The fonts are still the four bundled ones. More would mean shipping each in
  the worker image and the SPA.
- Every client that saves settings must send the fonts it wants kept, since a
  settings save without them goes back to the template's.

## Alternatives considered

- **Make a template behind the scenes when a font is picked.** Lost: it fills
  the user's templates with copies they never named, against
  `RESUME_TEMPLATE_MAX`.
- **Keep the fonts in the résumé's options.** Lost: options are how it is
  written (metrics, reorder, trim), not how it looks, and export compares the
  look as a spec.
- **Only make "Make your own" easier to find.** Lost: it still asks for a
  name and a saved template to change one font.
