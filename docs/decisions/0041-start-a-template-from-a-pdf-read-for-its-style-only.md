# 0041. A template can start from a PDF, read locally for its style only

**Status:** Accepted — 2026-10-10.

## Context

ADR 0040 lets a user design a résumé template as a checked `TemplateSpec`.
Often what they have instead is an example: someone else's résumé whose look
they like. Copying that design exactly is neither possible nor wanted:

- **The renderer's safety.** Turning an uploaded PDF into HTML or CSS of its
  own would let a crafted file change the layout, hide text or reach the
  network (ADR 0007).
- **Fonts.** A PDF embeds subsets of its fonts, often commercial ones, and the
  worker sets type only in the fonts it has.
- **Someone else's data.** The file carries another person's name, contact
  details and work history. None of it should be stored or shown.
- **No AI.** The gateway takes text only. Reading the page by eye would need
  image input from every provider, priced per image, on the user's key.

## Decision

A PDF's style is read locally into a draft spec, and the user reviews it in the
editor before anything is saved.

- **Upload.** `POST /resume-templates/upload` takes a PDF only, under
  `TEMPLATE_UPLOAD_MAX_BYTES`. A Word file has no fixed layout to read.
  - The file goes to object storage under `users/{owner}/templatefiles/`.
  - A `TemplateReading` (`resume.template_reading`, RLS, migration 0037) is
    recorded as `reading`, and `resume.read_template` is queued on `docs`.
  - The editor polls `GET /resume-template-readings/{id}` (ADR 0006).
  - Nothing is parsed in a request handler.
- **Reading is local and spends nothing.**
  - `resume/infra/style_reader.py` walks the first page with pypdf, opened
    through `kernel.documents.open_pdf` under `TEMPLATE_UPLOAD_MAX_PAGES`.
  - For each run of text it records a `StyleRun`: font name, size, fill colour,
    position, a character count, whether it is in capitals, and the list marker
    it starts with. It never records the text.
  - `get_template_spec_from_runs` turns the runs into the draft:
    - the largest type is the name, and the most common size the body;
    - short runs in capitals or a bold face are the headings, or else the
      sizes between body and name;
    - two columns of runs, each with a fair share, make a sidebar on the side
      of the narrower one;
    - the list markers' colour, or else any colour that is not near grey, is
      the accent.
  - Font names map to the bundled fonts by kind: serif, sans, display or
    monospace.
  - A value that cannot be read, or that fails the checks, takes Organic's and
    is listed as defaulted. Lines and backgrounds are never read, so the rule
    always defaults. The sidebar's sections cannot be told without the text,
    so a sidebar starts with skills, flagged.
- **Nothing of the file is kept.** The file is deleted as soon as the job ends,
  whether it read or failed. A page with no text fails as `unreadable_file`.
  The run keeps only the draft and the names of the values read and
  defaulted. It never keeps text, a name, a font name or the file's name.
  `resume.forget_template_reading` is scheduled a day after the upload and
  deletes the run.
- **The user reviews it.** The editor opens on the draft and says what it read
  ("We read: a left sidebar, a serif name and its accent colour."). Each field
  is marked as read from the file, or as Organic's to check. Before the upload
  it says that only the style is read, and that a very designed page comes out
  as the nearest of four layouts. Nothing is a template until it is saved
  through `POST /resume-templates`, under ADR 0040's checks.

## Consequences

Easier:

- A user gets near a look they like without designing it value by value, and
  nothing of the stranger's résumé reaches our storage beyond the minute it
  takes to read it.
- It spends nothing and needs no model.

Harder:

- It reads a style, not a copy. Photos, icons, rules, tinted panels and three
  columns are lost or folded into the nearest of four layouts.
- Reading a layout from text positions is a heuristic. Some files will be
  misread, and the review step is the only thing that catches it.
- Another upload to cap and test. A malformed PDF is parsed on the worker,
  as résumés and postings of your own already are.
- A user can upload a résumé they have no right to. Only its style is kept,
  but the upload itself still happens.

## Alternatives considered

- **Convert the PDF to HTML and CSS and render that.** Lost: it reopens
  everything ADR 0007 closed, and the fonts are not ours to embed.
- **Ask the user's model to describe the page.** Lost for now: the gateway is
  text only, and an image call is a spend on every try. It stays an open
  question once the gateway takes images.
- **Keep the file for a second try.** Lost: it is someone else's personal data,
  and the user can upload it again.
