# 0038. Make the PDF renderer the source of a résumé's look, and download the export directly

**Status:** Accepted — 2026-10-08. Amends [0007](0007-render-resume-pdfs-with-weasyprint.md).

## Context

The Résumé tab shows a preview, and Export as PDF renders the saved version
on the worker's `docs` queue (ADR 0007). They were two renderings that shared
only three colours, copied by hand: `ResumePage` in the SPA, styled by
`app.css`, and `render_html` in `advisor/resume/infra/render.py`. What a user
downloaded was not what they saw:

- **Fonts.** The preview set the name and job titles in Caprasimo and the text
  in Figtree, the design system's fonts, which the SPA hosts itself. The PDF
  used DejaVu Serif and DejaVu Sans, the only fonts in the worker image; the
  renderer fetches nothing, so it could not load the web fonts.
- **Trimming.** "Trim to one page" cut the PDF to 3 bullets per position and
  12 skills. The preview always showed everything.
- **Size.** The preview was a card of whatever width the screen gave it,
  sized in pixels. The PDF is A4 with 18/17mm margins, sized in points.
- **Details.** Bullets were drawn differently, and the preview's skills
  heading said "ordered for this role".

Export was also two steps: the SPA polled until the export was ready, then
showed a "Download the PDF" link, signed for five minutes and not signed
again, so it could expire before it was clicked. Every click rendered and
stored another PDF, and the trim was read when the worker rendered, not when
the user clicked.

## Decision

The PDF renderer's definition is the one look, and Export downloads the file.

- **The PDF uses the design system's fonts.** Caprasimo 400 and Figtree 400
  and 800 are installed in the worker image under `/usr/local/share/fonts/jsa`
  (from `backend/assets/fonts`, the SPA's WOFF2 files converted to TTF with
  their family names corrected), where fontconfig finds them. `render_html`
  names them by family, so the renderer still fetches nothing. DejaVu stays as
  the fallback for letters outside their Latin subset.
- **One definition of each template.** `TEMPLATE_LOOKS` in
  `resume/domain/template_look.py` holds each template's rule, colours, fonts,
  name and note; `constants.py` holds the page, the type sizes in points and
  the trim limits. `render_html` reads them, and `GET /resume-templates`
  (`ResumeTemplatePage`, ADR 0014) serves them. The SPA's own list of
  templates is gone.
- **The preview is laid out as the page is.** It is A4 in proportion, sized in
  the PDF's points scaled to its width (container query units), with the
  PDF's margins and list markers, and a line where each A4 page ends. With
  trim on it drops what the PDF drops, and says how much. The source notes
  and the rewritten-line highlight are the app's, shown only when asked for,
  and "ordered for this role" moves outside the page.
- **Export downloads the file.** Rendering stays on the worker. When an
  export is ready, `GET /resume-exports/{id}` signs its link with
  `Content-Disposition: attachment` and a file name — "<name> — <role>.pdf",
  ASCII with a UTF-8 `filename*` (`kernel.storage.attachment_disposition`) —
  and the SPA sends the browser to it at once. No link is shown. The button
  reads "Rendering…" while it waits.
- **An unchanged export is reused.** An export records the trim it was asked
  for (migration 0034), read when Export is clicked, as the template already
  was. Export on a version, template and trim that already have a ready
  export returns it, and nothing is queued.

## Consequences

Easier:

- What is downloaded is what was previewed: the same fonts, sizes, margins,
  markers and trimming, from one definition.
- A template is data, which the next steps (templates of the user's own)
  build on.
- The download link cannot expire before it is used, and a second click on
  an unchanged version costs nothing.

Harder:

- Close, not identical: the browser and Pango lay text out with different
  engines, so a line can still break one word apart, and the page markers are
  where A4 pages end, not a promise of where the PDF breaks.
- Font files in the image (about 85 KB), converted from the SPA's. A new
  weight or a fuller character set is an image change, and the two copies must
  be kept in step.
- Their Latin subset means a name in another script is set in DejaVu, or in
  nothing if DejaVu lacks it (Chinese or Japanese), in the PDF as on screen.
- A browser that blocked a download started after a wait would leave the
  user with nothing to click. Major browsers allow a navigation to an
  attachment; Safari and Firefox need checking by hand.
- The SPA makes one more request before it can draw the page.

## Alternatives considered

- **Render the preview from the PDF's HTML in an iframe.** Exact, but the
  page is edited in place, which an iframe of server-made HTML cannot do
  without rebuilding the editor inside it. Lost; "Preview the PDF" stays open
  as an addition.
- **Load the web fonts into WeasyPrint by URL.** Lost: the renderer refuses
  every fetch on purpose, so nothing in a résumé can make it reach the
  network.
- **Keep the link, and re-sign it on click.** Two steps for one action, which
  the user asked to be one.
- **Stream the PDF from the api.** Lost: rendering is CPU and memory, kept off
  request handlers (ADR 0007).
