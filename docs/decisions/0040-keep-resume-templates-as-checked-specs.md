# 0040. A résumé template is a checked spec, and a user can keep their own

**Status:** Accepted — 2026-10-09.

## Context

ADR 0038 made the PDF renderer the source of a résumé's look: two looks,
Organic and Plain, served by `GET /resume-templates` so the preview draws the
page the PDF prints. That left a closed `Template` enum and a check constraint
(`template IN ('organic', 'plain')`). A user who wanted a sidebar, another
typeface or their own colours had no way to get one.

ADR 0007 keeps the renderer safe: every value of a résumé is escaped, and
nothing is fetched. A template of the user's own is input too, so it must not
reach the renderer's HTML or CSS as text either.

## Decision

A template is a `TemplateSpec` (`resume/domain/template_spec.py`): checked
values, never markup. Each value is limited to what both the renderer and the
SPA's preview draw:

| Value | Allowed |
|---|---|
| `layout` | `single_column`, `header_band`, `sidebar_left`, `sidebar_right` |
| `heading_font`, `body_font` | `TEMPLATE_FONTS`: Caprasimo, Figtree, DejaVu Serif, DejaVu Sans Mono |
| `accent_color`, `name_color`, `text_color`, `rule_color` | `#rrggbb`; the name and the text at least 4.5:1 on white (`MIN_CONTRAST`) |
| `rule` | `none`, `thin`, `thick` |
| `name_pt`, `heading_pt`, `body_pt` | `NAME_PT_RANGE`, `HEADING_PT_RANGE`, `BODY_PT_RANGE` |
| `sidebar_kinds` | list sections only: skills, certifications |
| `heading_case` | `upper`, `as_written` |
| `bullet` | `dot`, `dash`, `none` |

An entry's title, the contact line and small print follow the body size
(`get_derived_pt`), as the built-in looks always did. `from_dict` checks every
value, whether sent by the SPA or read back from the database.

- **The built-in templates are specs.** `BUILT_IN_TEMPLATES` holds Organic and
  Plain, drawn exactly as before. Plain's rule (`#cfcac5`) differs from its
  bullets (`#9b9691`), which is why the rule has its own colour.
- **A user keeps their own.** `CustomTemplate` (`resume.custom_template`, under
  row-level security) is a name and a spec. Each user can keep up to
  `RESUME_TEMPLATE_MAX` of them (default 10).
- **A résumé is set in exactly one template.** That is either a built-in
  `template` or a `custom_template_id`, enforced by check constraint
  `ck_resume_look`. The wire carries one template id: a built-in name or the
  custom template's uuid.
- **Deleting a template moves its résumés to Organic** in the same
  transaction. The foreign key refuses a delete that forgets to.
- **An export records the spec it rendered** (`resume.export.spec`). Reuse
  compares specs, not ids, so a template edited since an export renders
  again, and a stored PDF keeps the look it was rendered in.
- **The routes.**
  - `GET /resume-templates` lists the built-in templates, then the user's own.
    Each comes with its spec, `is_built_in`, the derived sizes, the rule and
    the band tint.
  - `GET /resume-templates/limits` gives the editor its lists and ranges.
  - `POST`, `PUT /{id}` and `DELETE /{id}` keep, change and delete a template
    of the user's own.
- **The renderer and the preview draw every layout.**
  - A sidebar holds the contact line and the list sections the spec sends
    there. It comes first only on the left.
  - A header band is the accent at one part in eight, on white.
  - The preview sets DejaVu Serif and Mono from Latin subsets of the worker
    image's own files, so both set the same type.
- **The editor.** "Make your own" opens a copy of the chosen template, and the
  page previews every change. A colour too light to read is named and cannot
  be saved. Beside the sidebar layouts it says that some applicant-tracking
  systems read a sidebar out of order.

This amends ADR 0007, which kept the look in the renderer alone, and ADR 0038,
whose two looks are now two specs among a user's own.

## Consequences

Easier:

- A new look is data. Nothing a user chooses becomes CSS until it has been
  checked against an enum, a range or the hex pattern.
- A PDF exported before a template changed keeps meaning what it showed.

Harder:

- Every layout is built twice, in `render_html` and in the preview. A fifth
  layout costs more than a new colour did.
- A user can make an ugly template. The checks keep it readable, not
  handsome.
- Fonts are what we ship. Someone who wants a particular typeface gets the
  nearest one on the list.
- `wiring.models.OWNER_ZONE_TABLES` is now listed referencing tables first,
  because purging a user's rows in name order would delete a template before
  the résumés that name it.

## Alternatives considered

- **Let a user upload CSS or an HTML template.** Lost: it would undo ADR
  0007. A stylesheet can hide text, reorder the page, or reach the network
  through `url()`, and sanitising CSS is a contest we would lose.
- **Free colours and sizes with no contrast or range check.** Lost: the
  renderer would draw them, but a résumé printed in light grey on white fails
  the person it is for. 4.5:1 is WCAG AA for normal text.
- **Reuse an export by template id.** Lost: an edited template keeps its id,
  so a later export would hand back a PDF in the old look.
- **Cascade the delete to résumés, or set their template to null.** Lost: the
  first destroys work, and the second breaks the one-template rule.
