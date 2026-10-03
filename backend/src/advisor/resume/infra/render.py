"""Résumé export: content to HTML to PDF (ADR 0007, ADR 0038).

Export is presentation, not a domain rule (section 2.9). How each template
looks is the domain's ``TEMPLATE_LOOKS``, which the SPA's preview reads too,
and the page's sizes are the domain's constants, so the PDF is the page the
user previewed. Type is set in the design system's Caprasimo and Figtree,
installed in the image where fontconfig finds them, with DejaVu for anything
outside their Latin subset. Every value is escaped and nothing external is
referenced — no fonts, images or stylesheets are fetched — so a résumé's text
can never make the renderer reach the network. The grey source notes stay in
the app; a résumé sent to a company does not carry them.
"""

from __future__ import annotations

from html import escape

from advisor.resume.domain import (
    TRIMMED_BULLETS,
    TRIMMED_SKILLS,
    Options,
    ResumeContent,
    Template,
    get_template_look,
)
from advisor.resume.domain.constants import (
    BODY_PT,
    CONTACT_PT,
    FALLBACK_FONT,
    HEADING_PT,
    NAME_PT,
    PAGE_MARGIN_SIDE_MM,
    PAGE_MARGIN_TOP_MM,
    SMALL_PT,
    TITLE_PT,
)


def render_html(content: ResumeContent, *, template: Template, options: Options) -> str:
    look = get_template_look(template)
    heading = f'"{look.heading_font}", "{FALLBACK_FONT}", serif'
    body = f'"{look.body_font}", "{FALLBACK_FONT}", sans-serif'
    skills = content.skills[:TRIMMED_SKILLS] if options.trim else content.skills

    positions = []
    for position in content.experience:
        bullets = position.bullets[:TRIMMED_BULLETS] if options.trim else position.bullets
        items = "".join(f"<li>{escape(b.text)}</li>" for b in bullets)
        title = " — ".join(escape(part) for part in (position.title, position.org) if part)
        positions.append(
            '<section class="job">'
            '<div class="job-head">'
            f'<span class="job-title">{title}</span>'
            f'<span class="job-when">{escape(position.when)}</span>'
            "</div>"
            f"<ul>{items}</ul>"
            "</section>"
        )

    skill_items = "".join(f'<span class="skill">{escape(s)}</span>' for s in skills)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(content.name)}</title>
<style>
@page {{ size: A4; margin: {PAGE_MARGIN_TOP_MM}mm {PAGE_MARGIN_SIDE_MM}mm; }}
body {{ font-family: {body}; font-size: {BODY_PT}pt; color: #201e1d;
       background: #ffffff; line-height: 1.5; margin: 0; }}
header {{ border-bottom: {look.rule}; padding-bottom: 10pt; margin-bottom: 14pt; }}
h1 {{ font-family: {heading}; font-size: {NAME_PT}pt; line-height: 1.1;
     color: {look.name_color}; margin: 0; font-weight: 400; }}
.contact {{ font-size: {CONTACT_PT}pt; color: #5a5550; margin-top: 4pt; }}
h2 {{ font-size: {HEADING_PT}pt; letter-spacing: 0.1em; text-transform: uppercase;
     font-weight: 800; color: {look.name_color}; margin: 14pt 0 6pt; }}
.summary {{ margin: 0; }}
.job {{ margin-bottom: 10pt; page-break-inside: avoid; }}
.job-head {{ display: flex; justify-content: space-between; gap: 12pt; }}
.job-title {{ font-family: {heading}; font-size: {TITLE_PT}pt; }}
.job-when {{ font-size: {SMALL_PT}pt; color: #6b6560; white-space: nowrap; }}
ul {{ margin: 4pt 0 0; padding-left: 12pt; }}
li {{ margin-bottom: 3pt; }}
li::marker {{ color: {look.dot_color}; }}
.skills {{ display: flex; flex-wrap: wrap; gap: 5pt; }}
.skill {{ font-size: {SMALL_PT}pt; padding: 2pt 8pt; border-radius: 999px;
         background: #f3f1ee; color: #3d3a36; }}
</style></head>
<body>
<header>
<h1>{escape(content.name)}</h1>
<div class="contact">{escape(" · ".join(p for p in (content.headline, content.contact) if p))}</div>
</header>
<h2>Summary</h2>
<p class="summary">{escape(content.summary)}</p>
<h2>Experience</h2>
{"".join(positions)}
<h2>Skills</h2>
<div class="skills">{skill_items}</div>
</body></html>"""


def render_pdf(html: str) -> bytes:
    """Worker ``docs`` queue only: rendering is CPU and memory, never a request."""
    # Imported here so the api, which never renders, does not load Pango.
    from weasyprint import HTML
    from weasyprint.urls import FatalURLFetchingError, URLFetcher

    class NoFetching(URLFetcher):  # type: ignore[misc]
        """Nothing in a résumé should be fetched; anything that tries stops it."""

        def fetch(self, url: str, headers: object = None) -> object:
            raise FatalURLFetchingError(f"export does not fetch external resources: {url[:80]}")

    try:
        document = HTML(string=html, url_fetcher=NoFetching(fail_on_errors=True))
        return bytes(document.write_pdf())
    except FatalURLFetchingError as exc:
        raise ValueError(str(exc)) from exc
