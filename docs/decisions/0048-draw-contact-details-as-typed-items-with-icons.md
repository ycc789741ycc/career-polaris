# 0048. Contact details are typed items, drawn with icons

**Status:** Accepted — 2026-10-13.

## Context

A résumé's contact line was one free-text string, `ResumeContent.contact`,
which the model copies from an uploaded résumé ("maya@example.com · +49 151 …
· github.com/maya"). The page and the PDF printed it as plain text beside the
headline. A user wanted each detail drawn with its icon — email, phone,
GitHub, LinkedIn — as résumés commonly are, and to add or change them on the
page.

An icon needs to know what each detail is. A string does not say.

## Decision

Contact details are typed items, each drawn with its kind's icon.

- **Typed items.** `ResumeContent.contacts` is a tuple of `ContactItem(kind,
  value)` (`resume/domain/contact.py`), at most `MAX_CONTACTS` (8), each value
  non-empty and at most `MAX_CONTACT` (200) characters. `ContactKind` is
  email, phone, github, linkedin, website or location.
- **Read from the model's line by rules.** The prompts keep asking for a
  `contact` string, as an uploaded résumé has it. `get_contact_items` splits it
  on the separators résumés use (`·`, `|`, `,`, `;`, `•`, new lines) and
  classifies each piece by its shape: an address with `@` is email, a
  `github.com` or `linkedin.com` link is that, seven or more digits is a phone,
  another domain is a website, anything else a location. No prompt changes, and
  no model call decides a kind. The chat, shown the items, may answer with
  `contacts` instead, kept as they are.
- **Icons drawn inline, the same everywhere.** `CONTACT_ICONS` holds each
  kind's icon as the path of a 24-unit square SVG: GitHub and LinkedIn from
  Simple Icons (CC0), the rest from Material Icons (Apache 2.0).
  `render_html` draws each item as an inline SVG in the template's accent
  colour, then its text, so the PDF fetches nothing. `GET
  /resume-templates/limits` serves the same paths to the SPA, so the preview
  draws what the PDF draws (ADR 0038).
- **Edited in place.** Each item's text is edited on the page, and cleared to
  nothing, it goes. Its icon is also its kind menu. "+ Add contact" adds one.
  A link is shown as text and never made a live link, as ADR 0039 does for
  entry links.
- **A template read from a PDF still finds its columns.** An icon moves its
  line's text in by about 2% of the page, which split a sidebar's runs across
  starting points and hid the column from ADR 0041's reader. The reader now
  counts runs by the band of the page they start in (`COLUMN_BAND`, 4%) and
  places a column at its leftmost run. A résumé from elsewhere with icons
  reads the same way.
- **Migration 0042** rewrites every saved version and chat proposal from
  `contact` to `contacts`, in Python over the rows with row-level security
  lifted, with its own copy of the rule. Its downgrade joins the items back
  with " · ". `from_dict` reads only the new shape.

## Consequences

Easier:

- Each contact detail is drawn with its icon in the preview and the PDF alike,
  and a user can add one, change its kind or remove it without retyping a line.
- A new kind is one enum member, one icon path and one label.

Harder:

- The classification is a guess from shape. "Berlin, Germany" splits into two
  locations, and a bare handle with no domain reads as a location; the user
  fixes either with the kind menu or by editing the text.
- The icon paths are third-party artwork carried in the code, under their
  licences.
- Every reader of stored content — the renderer, the preview, the chat, the
  SPA's types — reads a list where it read a string.

## Alternatives considered

- **Ask the model for typed contacts.** Lost: it costs a prompt version for a
  shape rules decide as well, and the line still comes from the uploaded
  résumé's text.
- **Keep the string and pick icons when drawing it.** Lost: the user could not
  correct a wrong kind, and the preview and the PDF would each have to parse it
  the same way.
- **Bundle an icon font.** Lost: a font adds to the worker image and the SPA,
  and inline SVG is already safe for the renderer, which refuses fetches.
