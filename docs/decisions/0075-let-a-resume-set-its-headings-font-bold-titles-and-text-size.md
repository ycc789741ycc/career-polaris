# 0075. A résumé may set its headings' font, bold titles and headings, and its text size

**Status:** Accepted — 2026-10-12.

## Context

ADR 0047 let a résumé set two fonts over its template's: "Titles in", for the
name and each entry's title, and "Text in", for everything else. Three things
stayed fixed by the template, and users asked for each:

- Section headings (EXPERIENCE, SKILLS…) printed in the body font, with no way
  to set them apart.
- The name and the entries' titles printed at weight 400; only headings were
  bold, at 800, always.
- The text size was the template's. Changing it meant making a template of
  one's own.

Every bundled family has a bold cut except Caprasimo, which is 400 only.
Asking WeasyPrint and the browser for a bold that does not exist makes each
fake one, differently, so the preview would stop matching the PDF.

## Decision

A résumé may also set, over whichever template it is set in, its section
headings' font, whether titles and headings are bold, and its text size.

- **In the spec.** `TemplateSpec` gains `section_font` (None: the body font,
  as before), `bold_titles` (default off) and `bold_headings` (default on), so
  every stored spec and every built-in prints as it did. `from_dict` reads a
  spec stored before them with those defaults. `get_title_weight` and
  `get_heading_weight` give 700 when bold, and 400 in a font listed in
  `FONTS_WITHOUT_BOLD` (Caprasimo); a family with no 700 takes its nearest
  heavier cut (Figtree's 800).
- **On the résumé.** `TailoredResume` keeps `section_font`, `bold_titles`,
  `bold_headings` and `body_pt` beside ADR 0047's fonts, each None to keep
  the template's, as one `OwnLook`. `update_look` checks it
  (`assert_own_look_valid`: fonts from `TEMPLATE_FONTS`, the size in
  `BODY_PT_RANGE`), and `get_spec_with_look` lays it over the template's spec,
  replacing `get_spec_with_fonts`. Migration 0057 adds the four columns, with
  checks on the font and the size.
- **Set with the settings.** `PUT /tailored-resumes/{id}/settings` takes the
  four beside ADR 0047's fonts; left out, each goes back to the template's.
  `GET /resume-templates/limits` serves `fonts_without_bold`.
- **One look everywhere.** The PDF sets the headings in their font and the
  weights from the spec, and the derived sizes (an entry's title, the contact
  line, small print) follow the text size, as they always followed the
  template's. An export stores the spec it rendered, so reuse (ADR 0038) tells
  a changed look from the last. The preview reads the same values.
- **The SPA.** The Layout card has "Titles in" with "Bold titles", "Headings
  in" with "Bold headings", and "Text in" with "Text size", half a point
  apart. A Bold switch is off, and says why, while its font has no bold cut.
- **Not read from a file.** A template started from a PDF (ADR 0041) never
  reads these three from it; they keep Organic's without being flagged.

This amends ADR 0047.

## Consequences

Easier:

- Headings, weights and size change in one choice each, with no template to
  make.
- Every existing résumé, template and export reads and prints exactly as
  before.

Harder:

- A résumé's look has more of its own over its template's. A user who edits a
  template's size sees no change on a résumé that set its own.
- `FONTS_WITHOUT_BOLD` is kept in the backend and, for the first paint, in
  the SPA; a test holds each to fontconfig and to the limits, but a new font
  must be added to both.
- A larger text size can push a one-page résumé onto two; the page's A4 line
  shows it, nothing stops it.

## Alternatives considered

- **Only on templates of one's own.** Lost: the same objection ADR 0047 met —
  a name and a saved template to change one size.
- **A weight per font (400–800) rather than Bold.** Lost: the bundled cuts
  are 400 and 700 (Figtree 800); any other weight would be faked.
- **Fake bold in Caprasimo.** Lost: WeasyPrint and the browser embolden
  differently, and the preview would stop being the PDF.
- **Sizes for the name and headings too.** Not now: asked for was the text;
  a template of one's own still sets the others.
