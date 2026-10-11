# 0078. Keep a résumé's text settings to the text, and let it size its titles and headings

**Status:** Accepted — 2026-10-12. Amends [0075](0075-let-a-resume-set-its-headings-font-bold-titles-and-text-size.md).

## Context

ADR 0075 gave a résumé "Headings in", Bold titles and headings, and a "Text
size" over its template's. Two things it left coupled:

- Section headings with no font of their own fall back to the body font. Laid
  over a template that names no heading font — every built-in one — the
  fallback became the résumé's own "Text in" font, so changing the text
  changed the headings.
- An entry's title has never had a size of its own: it is the text size plus
  a point. So "Text size" moved every entry title.

Users asked for "Text in" to be the text alone, and for the name, the titles
and the headings to have sizes of their own.

## Decision

- **The text settings reach only the text.** "Text in" and "Text size" cover
  everything that is neither a title nor a heading: lines, summary, skills,
  dates, the contact line. `get_spec_with_look` pins the headings' font and
  the entry titles' size to the *template's* own, worked out before the
  résumé's text settings are laid on, when the résumé changes the text and
  sets none for them. With nothing changed it returns the template's spec
  unchanged. The contact line and small print still follow the text size,
  since they are text.
- **An entry title's size in the spec.** `TemplateSpec.title_pt` is None by
  default; `get_title_pt` returns it, or the text size plus a point as before,
  and `get_derived_pt` uses it. A spec stored without it reads None and prints
  as it did. A template of one's own may send it (`TemplateDesign.title_pt`).
- **Three sizes on the résumé.** `name_pt`, `title_pt` and `heading_pt` join
  `body_pt` on `TailoredResume` and `OwnLook`. Each is None to keep the
  template's, or in its range: the name's `NAME_PT_RANGE` and the headings'
  `HEADING_PT_RANGE`, as a template's, and an entry title's new
  `TITLE_PT_RANGE` (9–14). Migration 0059 adds the columns with checks.
  `GET /resume-templates/limits` serves `title_pt_range`.
- **The SPA.** In the Layout card, each font row carries its sizes: "Titles
  in" has Name and Title, "Headings in" and "Text in" a Size. The name steps
  a point at a time, the rest half a point. The first option of each says the
  template's size.

## Consequences

Easier:

- Changing the text's font or size no longer reshapes the headings or titles.
- The name, titles and headings can be sized without a template of one's own.

Harder:

- A résumé's look has three more values over its template's, and a template's
  own edits to them do not reach a résumé that set its own.
- A résumé with a changed text size now pins its titles' size into the spec it
  exports, so an export rendered before this one is not reused once.

## Alternatives considered

- **Change only bullet lines with "Text in".** Lost: the summary, skills and
  dates would stay in the template's font beside lines in another, which reads
  as a mistake; users chose all body text.
- **One "Title size" scaling the name with it.** Lost: the name and an entry
  title differ by a factor of two, and a single control could not set either
  where the user wants it.
